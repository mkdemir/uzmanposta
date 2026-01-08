# Uzman Posta Mail Event Logger

<p align="center">
<img src="assets/uzmanposta-logo.png" alt="Uzman Posta Logo" width="400"/>
</p>

## Genel Bakış

**Uzman Posta Mail Event Logger**, Uzman Posta API üzerinden mail olaylarını (gelen/giden), karantina ve kimlik doğrulama loglarını toplamak ve kaydetmek için tasarlanmış, prodüksiyon seviyesinde bir Python betiğidir. Eşzamanlılık limitleri ile yüksek performanslı paralel işlemeyi, sağlam veri bütünlüğünü destekler ve Cron gibi otomatik ortamlar için optimize edilmiştir.

## Temel Özellikler

- ✅ **Sıralı İşleme**: Mutlak veri bütünlüğü için loglar kesin kronolojik sırayla kaydedilir.
- ✅ **Dinamik Dosya İsimlendirme**: Log dosya isimleri, `{domain}_{type}_%Y-%m-%d_%H.log` formatında ve dinamik yer tutucu desteğiyle standartlaştırılmıştır.
- ✅ **Otomatik Temizlik**: Disk kullanımını kontrol altında tutmak için hem mesaj hem de hata logları için otomatik saklama (retention) politikaları vardır.
- ✅ **Yüksek Performanslı Paralellik**: Yapılandırılabilir işçi limitleri (`--max-workers`) ile birden fazla domain için logları paralel olarak çeker.
- ✅ **Eşzamanlı Detay Çekimi**: Her domain içinde çoklu iş parçacığı (thread) kullanarak detaylı mail loglarını (gönderen, alıcı, durum) hızlıca çeker.
- ✅ **Çapraz Platform Dayanıklılığı**: Windows'a özgü dosya kilitleme ve atomik yazma sorunları (`[WinError 5]`) için düzeltmeler içerir.
- ✅ **Cron İçin Optimize Edildi**: Zamanlanmış görevlerde hata oluşmasını önlemek için dahili yollar otomatik olarak betiğin bulunduğu dizine göre çözümlenir.
- ✅ **Atomik Pozisyon Takibi**: Çökme veya manuel durdurma durumunda bile işleme kaldığı yerden eksiksiz devam eder.
- ✅ **Oturum Yönetimi**: `requests.Session` ile kalıcı HTTP bağlantıları (Keep-Alive) kullanır.
- ✅ **İzleme**: Alan adı bazında gerçek zamanlı kalp atış (heartbeat) dosyaları ve kapsamlı metrikler sunar.

## Gereksinimler

- Python 3.8+
- `requests` kütüphanesi (`pip install requests`)
- Geçerli bir Bearer token'a sahip Uzman Posta API erişimi

## Hızlı Başlangıç

```bash
# Bağımlılıkları yükleyin
pip install -r requirements.txt

# Yapılandırmadaki tüm bölümleri listele
python3 uzmanposta.py --list

# Tüm domainleri paralel çalıştır (varsayılan 5 işçi ile)
python3 uzmanposta.py --all --parallel

# Tüm domainleri belirli bir eşzamanlılık limitiyle çalıştır
python3 uzmanposta.py --all --parallel --max-workers 3

# Belirli bir domain bölümünü çalıştır
python3 uzmanposta.py --section "MailLogger:domain-outgoing"
```

## Komut Satırı Argümanları (CLI)

| Argüman | Açıklama | Varsayılan |
|----------|-------------|---------|
| `--config YOL` | INI yapılandırma dosyasının yolu. | `uzmanposta.ini` |
| `--section İSİM` | Sadece yapılandırmadaki belirli bir bölümü çalıştırır. | - |
| `--all` | `[MailLogger:*]` ile başlayan tüm bölümleri işler. | `False` |
| `--parallel` | Bölümler için çoklu iş parçacığı (multi-threading) işlemesini etkinleştirir (`--all` gerektirir). | `False` |
| `--max-workers N` | Üst düzey görevler için maksimum paralel işçi sayısı. | `5` |
| `--list` | Keşfedilen tüm yapılandırma bölümlerini listeler ve çıkar. | - |

## Yapılandırma (`uzmanposta.ini`)

Betik, yapılandırma için bir INI dosyası kullanır. Ortak ayarlar için `[DEFAULT]` bölümünü kullanabilirsiniz.

```ini
[DEFAULT]
# Genel varsayılanlar (dahili varsayılanları kullanmak için yorum satırı yapılmıştır)
# log_directory = ./output
# max_parallel_details = 2
log_file_name_format = {domain}_{type}_%Y-%m-%d_%H.log

[MailLogger:ornek-giden]
api_key    = SIZE_OZEL_API_ANAHTARI
domain     = ornek.com.tr
type       = outgoinglog
category   = mail
start_time = 1734876000
```

### Gelişmiş Ayar Seçenekleri

| Seçenek | Açıklama | Varsayılan |
| --- | --- | --- |
| `api_key` | **Zorunlu** Domain için API Anahtarı | - |
| `domain` | **Zorunlu** Alan adı | - |
| `type` | Log tipi (`incominglog`, `outgoinglog`, `quarantine`, vb.) | `outgoinglog` |
| `category` | API kategorisi (`mail`, `quarantine`, `authentication`) | `mail` |
| `start_time` | Logların çekilmeye başlanacağı Unix zaman damgası (belirtilmezse ŞU AN) | `Şu An` |
| `log_file_name_format` | Yer tutucularla log dosya formatı | `{domain}_{type}_%Y-%m-%d_%H.log` |
| `error_log_file_name` | Hata log dosyaları için format | `errors_%Y-%m-%d_%H.log` |
| `error_log_retention_count` | Saklanacak son hata logu sayısı | `2` |
| `max_parallel_details` | Domain başına eşzamanlı detay çekme işçi sayısı | `2` |
| `use_session` | Bağlantı havuzunu (connection pool) etkinleştir | `True` |

## Çıktı Yapısı

Betik, bulunduğu konuma göre temiz bir dizin yapısını otomatik olarak korur:

```text
/proje-klasoru/
├── positions/             # Her bölüm için kontrol noktaları (kaldığı yer)
├── locks/                 # Eşzamanlı çalışmayı önlemek için kilit dosyaları
└── output/
    └── ornek.com.tr/
        └── mail/
            └── outgoinglog/
                ├── ornek.com.tr_outgoinglog_2025-12-25_14.log  # Ana veri logu
                ├── messages_2025-12-25_14.log                 # Detaylı operasyon logları
                ├── errors_2025-12-25_14.log                   # Hata logları
                └── ornek.com.tr-outgoing_heartbeat.json       # Sağlık durumu
```

## Dağıtım (Cron)

Betik Cron için tasarlanmıştır. Farklı bir çalışma dizininden çalıştırılsa bile yapılandırma ve çıktı klasörlerini otomatik olarak bulur.

```bash
# Her 5 dakikada bir (5 işçi ile paralel çalışma)
*/5 * * * * /usr/bin/python3 /opt/uzmanposta/uzmanposta.py --config /opt/uzmanposta/uzmanposta.ini --all --parallel --max-workers 5
```

## İzleme ve Metrikler

Betik, iki ana mekanizma üzerinden gerçek zamanlı izleme sağlar:

1.  **Heartbeat (Kalp Atışı) Dosyaları**: Her bölüm, çıktı dizininde bir `{bölüm}_heartbeat.json` dosyası tutar. Bu dosya şunları içerir:
    - `status`: `running` (çalışıyor), `completed` (tamamlandı) veya `error` (hata).
    - `last_heartbeat`: Son güncelleme zaman damgası.
    - `pid`: İşlem kimliği (Process ID).
    - `metrics`: Güncel işleme istatistikleri.
2.  **Özet İstatistikler**: Her çalışma sonunda aşağıdakileri içeren bir özet loglanır:
    - İşlenen toplam log sayısı.
    - API başarı/hata oranları.
    - Ortalama/Min/Max API yanıt süreleri.
    - Verim (log/saniye).

## Veri Bütünlüğü ve Kaldığı Yerden Devam Etme

### Pozisyon Takibi

Betik, hiçbir logun kaçırılmamasını veya yinelenmemesini sağlamak için atomik pozisyon takibi kullanır.

- **Konum**: `./positions/{bölüm}.pos`
- **Mekanizma**: Her başarılı toplu yazma işleminden sonra, işlenen son kaydın zaman damgası kaydedilir. Yeniden başlatıldığında, betik tam olarak bu zaman damgasından devam eder.

### Dosya Kilitleme

Veri bozulmasını önlemek için çapraz platform destekli bir dosya kilitleme mekanizması kullanılır:

- **Konum**: `./locks/{bölüm}.lock`
- **Davranış**: Bir bölüm zaten işleniyorsa (örneğin önceki bir Cron görevi hala çalışıyorsa), yeni örnek o bölümü atlar ve bir mesaj loglar.

## Sorun Giderme

### `[WinError 5] Access is denied`
Bu, Windows üzerinde birden fazla iş parçacığı aynı anda dosya yazmaya/yeniden adlandırmaya çalışırken, antivirüs tarayıcısı veya işletim sisteminin dosyaları anlık olarak kilitlemesi sonucu oluşan yaygın bir sorundur. Betik, bu geçici hatayı otomatik olarak işlemek için bir yeniden deneme mekanizması (`_safe_replace`) içerir.

### API Kısıtlaması ("Too Many Requests")
HTTP 429 hataları veya zaman aşımı görüyorsanız, eşzamanlılığı azaltın:
- `--max-workers` değerini düşürün (örneğin 5'ten 2'ye).
- `uzmanposta.ini` içindeki `max_parallel_details` değerini düşürün (örneğin 1 veya 2 yapın).

## Hukuki Uyarı

> [!IMPORTANT]
> **Veri Gizliliği ve Uyumluluk**
> Bu araç, hassas olabilecek e-posta metadata verilerini toplamak ve işlemek için tasarlanmıştır. Bu betiğin kullanımının yerel ve uluslararası veri koruma yasalarına uygunluğunu sağlamak kullanıcının sorumluluğundadır:
> - **KVKK** (Kişisel Verilerin Korunması Kanunu)
> - **GDPR** (Genel Veri Koruma Yönetmeliği)
> - **5271 Sayılı CMK** (Dijital Delil Elde Etme ve Koruma)
> - **Kurumsal Güvenlik Politikaları**
>
> Bu betiğin yanlış yapılandırılması veya yaygınlaştırılmasından kaynaklanan veri suistimalleri veya yetkisiz erişimlerden geliştiriciler sorumlu tutulamaz.

## Lisans

MIT Lisansı - Detaylar için [LICENSE](LICENSE) dosyasına bakınız.
