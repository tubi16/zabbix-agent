# Staj Agent — Linux TLS kurulumu

Çok site / active-only üretim kurulumu: [installation.md](../installation.md).
Sihirbazda Active-only seçeneği veya `install.py --active IP:PORT` kullanılır.

## Kolay kurulum (önerilen)

Repo klasöründe normal kullanıcıyla çalıştır:

```sh
python3 setup.py
```

Menüden **1: Server**, **2: Agent** veya **3: Sunucudan cihaz ekle** seç.
Mevcut repo kullanılır; yeniden klonlama gerekmez. Eksik paketler için onay
ve gerektiğinde sudo parolası istenir. SSH ve firewall ayarları değiştirilmez.

- **Server:** Yeni kurulumda Zabbix web, Grafana ve server portlarını sorar;
  Enter varsayılanı seçer. Parolaları otomatik üretir, Compose ayarlarını
  doğrular ve servisleri başlatmadan onay ister. Mevcut `.env` korunur.
- **Agent:** Eksik agent paketini onayla kurar. TLS için host adı, sunucudan
  güvenli alınan PSK dosyasının yolu ve sunucu IP adresi/alt ağlarını sorar.
- **Cihaz ekle:** Sunucu reposunda çalıştır. Cihaz adı, cihaz IP'si, sunucunun
  agent tarafından görülen IP'si, SSH hedefi ve agent repo yolu sorulur.
  PSK üretimi ve Zabbix kaydı otomatik yapılır; önce plan gösterilir.
  Hedefte Python 3 ve agent kurulu, sunucuda template hazır olmalıdır.

Agent kurulumu tek başına sunucuda host oluşturmaz. Otomatik kayıt için
sunucudaki **3** seçeneğini kullan. Grafana veri kaynağı ve host-sync token
ayarları aşağıdaki yönergelerde ayrıca tamamlanır.

Servis durdurma: sunucu klasöründe `sudo docker compose stop` (veriler korunur).
Agent geri alma: kurulum çıktısında belirtilen ilk yedek ve geri alma komutu.


Kurulu Zabbix agent veya agent2 servisini cihaza özel TLS-PSK ile yapılandırır.
Bu klasör ayrı bir Git reposuna alınabilir; sunucu reposuna veya Python
paketlerine bağımlı değildir. Zabbix/Grafana hesabı, API istemcisi, Admin
parolası, Docker ya da dashboard kodu içermez.

## Ön koşullar ve kapsam

- Linux üzerinde Python 3, systemd ve kurulu Zabbix agent/agent2 gerekir.
- İzleme template'i için Zabbix 7.4 veya daha yeni agent kullan.
- CPU, RAM, kök disk, veri kesilmesi ve yeniden başlama trigger'ları sunucudaki
  `Essential Items` / `Essential Items Active` template'inden hosta aktarılır.
  Telegram alıcı ve action ayarları Zabbix arayüzünde yapılır; agent tarafında
  bot token'ı veya ek bildirim script'i gerekmez.
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

`enroll.py` bu agent reposunda değil, **staj-server** reposunda
`zabbix/tls/enroll.py` konumundadır. Bu kullanım için iki repo da sunucu
yöneticisinin bilgisayarında klonlu olmalıdır. Örnek klasör düzeni:

```text
zabbix-project/
├── staj-server/zabbix/tls/enroll.py
└── staj-agent/install.py
```

Komutu `staj-server` klasöründen çalıştır; IP ve SSH kullanıcısını değiştir:

```sh
cd /sunucu/reponun/yolu/staj-server
python3 zabbix/tls/enroll.py --host YeniPC --address 172.16.53.150 --ssh kullanici@172.16.53.150 --server 172.16.53.132 --agent-source ../staj-agent
```

`--agent-source` bu agent reposunun kökünü, yani `install.py` dosyasının
bulunduğu klasörü gösterir. Repolar yan yana değilse tam yol ver.
Otomasyon hedefe sadece `install.py` ve cihaz anahtarını aktarır, kurulum
aşamalarını çalıştırır ve şifreli/şifresiz bağlantı testlerini yapar.
Hedef bilgisayara sunucu reposunun tamamını kopyalamak gerekmez.
Yalnızca bu agent reposunu klonladıysan üstteki **Bağımsız kullanım** bölümünü
izle; bu yöntem sunucuda host/PSK kaydını otomatik yapmaz.

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
