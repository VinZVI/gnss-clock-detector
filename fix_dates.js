// Quick test to see how Date works with this
const s = "Tue, 31 Mar 2026 00:05:00 GMT";
console.log("Old way:", s.replace('T',' ').slice(0,19));
const d = new Date(s);
console.log("New way:", d.toISOString().replace('T', ' ').slice(0, 19));
