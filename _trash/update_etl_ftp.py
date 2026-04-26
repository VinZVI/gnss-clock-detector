import re

with open('src/gnss_clock/ftp_client.py', 'r', encoding='utf-8') as f:
    ftp_content = f.read()

# Добавляем новую функцию для кандидатов статуса
candidates_status_func = """
def _candidates_status(dt) -> List[Tuple[str, Optional[str]]]:
    yy = dt.year % 100
    stem = f"{dt.day:02d}{dt.month:02d}{yy:02d}"
    return [
        (f"Const_{stem}.glo", None),
        (f"Stark_{stem}.hlt", None)
    ]
"""

# Вставляем перед _candidates
if "_candidates_status" not in ftp_content:
    ftp_content = ftp_content.replace('def _candidates(', candidates_status_func + '\ndef _candidates(')


# Обновляем парсинг: добавляем вызов _candidates_status и исправляем логику декодирования 
new_loop_logic = """
                    # 2. 6-часовые слоты (теперь ищем везде, не только в ultra)
                    current_candidates.extend(_candidates(dt, slot_h))
                    
                    # Статусы и паспорта
                    if subdir == "ultra":
                        current_candidates.extend(_candidates_status(dt))

                    # 3. Высокоточные 30с (только в final)
                    if subdir == "final":
                        from .gps_time import utc_to_gps_week
                        week, dow = utc_to_gps_week(dt)
                        current_candidates.append((f"Sta30s{week:04d}{dow}.clk", None))

                    for fname, compression in current_candidates:
                        key = f"{subdir}/{fname}"
                        if key in already_loaded:
                            logger.debug("  пропуск (уже загружен): %s", key)
                            break

                        if fname not in server_set:
                            continue

                        raw = _download(ftp, fname)
                        if raw is None:
                            continue

                        if fname.lower().endswith(".glo"):
                            text = raw.decode('cp1251', errors='replace')
                        elif fname.lower().endswith(".hlt"):
                            text = raw.decode('ascii', errors='replace')
                        else:
                            text = _decompress(raw, fname)

                        if text is None:
                            continue

                        yield fname, text, subdir
                        break
"""

# Ищем старый цикл и заменяем
# Ищем от "# 2. 6-часовые слоты" до "break"
start_str = "# 2. 6-часовые слоты (теперь ищем везде, не только в ultra)"
end_str = "yield fname, text, subdir\n                        break"
start_idx = ftp_content.find(start_str)
end_idx = ftp_content.find(end_str) + len(end_str)

if start_idx != -1 and end_idx != -1:
    ftp_content = ftp_content[:start_idx] + new_loop_logic.strip() + ftp_content[end_idx:]

with open('src/gnss_clock/ftp_client.py', 'w', encoding='utf-8') as f:
    f.write(ftp_content)


with open('src/gnss_clock/status_parsers.py', 'r', encoding='utf-8') as f:
    stat_content = f.read()

stat_content = stat_content.replace('def parse_glo(content_bytes):', 'def parse_glo(content_str):')
stat_content = stat_content.replace("    text = content_bytes.decode('cp1251', errors='replace')", "    text = content_str")

with open('src/gnss_clock/status_parsers.py', 'w', encoding='utf-8') as f:
    f.write(stat_content)


with open('src/gnss_clock/etl.py', 'r', encoding='utf-8') as f:
    etl_content = f.read()

new_etl = """
    for fname, text, subdir in file_iterator:
        file_key = f"{subdir}/{fname}"
        
        if fname.lower().endswith(".glo"):
            from .status_parsers import parse_glo
            from .models import SatelliteMeta, db
            records = parse_glo(text)
            stats["files_processed"] += 1
            with app.app_context():
                log = EtlLog(ftp_file=file_key, records_raw=len(records))
                db.session.add(log)
                for r in records:
                    meta = SatelliteMeta.query.get(r['sat_id'])
                    if not meta:
                        db.session.add(SatelliteMeta(**r))
                    else:
                        for k, v in r.items():
                            setattr(meta, k, v)
                log.status = "ok"
                log.finished_at = _utcnow()
                db.session.commit()
            logger.info(f"Loaded .glo meta for {len(records)} satellites")
            continue
            
        elif fname.lower().endswith(".hlt"):
            from .status_parsers import parse_hlt
            from .models import SatelliteStatusHistory, db
            records = parse_hlt(text)
            stats["files_processed"] += 1
            with app.app_context():
                log = EtlLog(ftp_file=file_key, records_raw=len(records))
                db.session.add(log)
                new_hist = 0
                for r in records:
                    exists = SatelliteStatusHistory.query.filter_by(
                        sat_id=r['sat_id'], start_epoch=r['start_epoch'], end_epoch=r['end_epoch']
                    ).first()
                    if not exists:
                        db.session.add(SatelliteStatusHistory(**r))
                        new_hist += 1
                log.records_new = new_hist
                log.status = "ok"
                log.finished_at = _utcnow()
                db.session.commit()
            logger.info(f"Loaded {new_hist} .hlt records")
            continue

        # Standard processing (CLK, SP3)
        records = parse_file(text, fname)
        stats["files_processed"] += 1
"""

start_idx = etl_content.find("    for fname, text, subdir in file_iterator:")
end_idx = etl_content.find("stats[\"files_processed\"] += 1\n        stats[\"records_raw\"] += len(records)")

if start_idx != -1 and end_idx != -1:
    end_idx += len("stats[\"files_processed\"] += 1\n        stats[\"records_raw\"] += len(records)")
    # replace block
    etl_content = etl_content[:start_idx] + new_etl.strip() + "\n        stats[\"records_raw\"] += len(records)\n" + etl_content[end_idx:]

with open('src/gnss_clock/etl.py', 'w', encoding='utf-8') as f:
    f.write(etl_content)

