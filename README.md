# Staj Agent — Linux TLS kurulumu

Kurulu Zabbix agent veya agent2 servisini cihaza özel TLS-PSK ile yapılandırır.
Bu klasör ayrı bir Git reposuna alınabilir; sunucu reposuna veya Python
paketlerine bağımlı değildir. Zabbix/Grafana hesabı, API istemcisi, Admin
parolası, Docker ya da dashboard kodu içermez.

## Ön koşullar ve kapsam

- Linux üzerinde Python 3, systemd ve kurulu Zabbix agent/agent2 gerekir.
- İzleme template'i için Zabbix 7.4 veya daha yeni agent kullan.
- Script agent paketini indirmez veya kurmaz; mevcut agent'ın TLS ayarlarını yapar.
- Cihazda yönetici yetkisi gerekir; yalnızca ilgili agent servisi yeniden başlatılır.
- Hostun gizli PSK dosyası sunucu yöneticisinden güvenli yolla alınmalıdır.
  Anahtarı Git'e veya mesajlara koyma; her cihazın anahtarı farklı olmalıdır.

## Bağımsız kullanım

Bu repoyu cihaza kopyala/klonla. Sunucu tarafından üretilmiş anahtarla:

```sh
sudo python3 install.py --host YeniPC --key /guvenli/yol/YeniPC.psk --server 172.16.53.132 --strict
```

`--server` agent'a gelen bağlantının kaynak IP'si/alt ağıdır. Cihazın kendi
IP'si değildir. IP'yi kendi ortamına göre değiştir. Birden fazla kaynak için
`--server` tekrar verilebilir. Script mevcut izinli kaynakları korur.

| Parametre | İşlev |
| --- | --- |
| `--host` | Teknik Zabbix host adı; 1–64 ASCII harf/rakam, nokta, alt çizgi veya tire |
| `--key` | 256-bit PSK içeren dosya; 64 hexadecimal karakter |
| `--server` | İzin verilecek sunucu IP'si/alt ağı; tekrar verilebilir |
| `--agent` | `auto`, `classic`, `agent2`; varsayılan `auto` |
| `--port` | Agent dinleme portu; verilmezse mevcut port korunur |
| `--strict` | Yalnızca PSK kabul et; otomasyonun son aşaması bunu kullanır |

`auto` tam bir aktif agent servisi bekler; iki agent birden aktifse seçim
yapmadan durur. Böyle bir durumda uygun `--agent` parametresini açıkça ver.

## Kurulum sırasında yapılanlar

1. Anahtar, host adı, agent servisi ve çakışan Include ayarları kontrol edilir.
2. Mevcut agent config'i zaman damgalı, root erişimli dosyaya yedeklenir.
3. Anahtar `/etc/zabbix/tls/staj-HOST.psk` konumuna root:zabbix `0640`
   izinleriyle kurulur; dizin `0750` olur.
4. `Hostname`, `Server`, `TLSPSKIdentity`, `TLSPSKFile`, `TLSConnect` ve
   `TLSAccept` ayarlanır. Verilmişse `ListenPort` da güncellenir.
5. Agent'ın `-T` testi başarılıysa ilgili servis yeniden başlatılır.

`TLSPSKIdentity=staj-HOST` gizli anahtarı seçen kimliktir; PSK'nın kendisi
değildir. TLS bağlantısında PSK bilgisi doğrulanır ve oturum trafiği şifrelenir.
Script API üzerinden Zabbix hostunu oluşturmaz; sunucuda aynı kimlik/anahtar
ayrıca tanımlanmalıdır. Web arayüzleri için HTTPS sağlamaz.

`--strict` olmadan ilk geçişte `unencrypted,psk` kabul edilir. Sunucu otomasyonu
önce PSK ile bağlantıyı doğrular, ardından bu scripti `--strict` ile tekrar
çağırır. Zaten strict olan bir agent, komut tekrar çalıştırıldığında şifresiz
moda gevşetilmez. Farklı bir anahtar sessizce mevcut anahtarın üzerine yazılmaz.

## Sunucu otomasyonuyla kullanım

Sunucu yöneticisi bu repoyu kendi bilgisayarında klonlayıp sunucu reposundaki
`enroll.py --agent-source /bu/reponun/yolu` seçeneğini kullanır. Otomasyon hedefe
sadece `install.py` ve cihaz anahtarını aktarır, kurulum aşamalarını çalıştırır
ve şifreli/şifresiz bağlantı testlerini yapar. Bu kullanımda hedef bilgisayara
sunucu reposunun tamamını kopyalamak gerekmez.

## Geri alma

Config doğrulaması başarısızsa eski dosya geri yüklenir ve restart yapılmaz.
Restart başarısızsa eski config geri yüklenip servis tekrar başlatılır.
Başarılı kurulumda ekrana yedek yolu ve geri alma komutu yazılır. **İlk**
kurulumun yedeğini kullan; son strict aşamasının yedeği ara ayarlara döndürür.
Sunucu tarafındaki TLS modu da eşleştirilmeden şifresiz moda dönme.
SSH, firewall ve diğer agent servisi bu script tarafından değiştirilmez.

## Testler

```sh
python3 -B -m unittest discover -s . -p 'test_*.py'
```

Gerçek TLS testi için Python'un TLS-PSK desteği ve yerel `zabbix_agentd` gerekir:

```sh
RUN_TLS_INTEGRATION=1 python3 -B -m unittest discover -s . -p 'test_real_tls.py'
```

Bu test yalnızca rastgele bir localhost portunda geçici agent başlatır;
mevcut servisi değiştirmez. Doğru anahtarın kabulünü, yanlış anahtarın ve
şifresiz bağlantının reddini kontrol edip geçici süreci kapatır.
