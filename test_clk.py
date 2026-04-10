import gzip
import ftplib
import gzip
import io

def get_file(name):
    ftp = ftplib.FTP('ftp.glonass-iac.ru')
    ftp.login()
    buf = io.BytesIO()
    ftp.retrbinary(f"RETR {name}", buf.write)
    ftp.quit()
    return buf.getvalue()

data = get_file('/MCC/PRODUCTS/26079/final/Sta24105.clk')
print("Sta24105.clk lines: ", len(data.split(b'\n')))
glonass = [line for line in data.split(b'\n') if b'AS R' in line or b' R05' in line]
print("GLONASS lines: ", len(glonass))
if glonass:
    print(glonass[0])
else:
    print("No GLONASS data in Sta24105.clk")

