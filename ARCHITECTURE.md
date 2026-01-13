# UzmanPosta Mail Logger - Kod Mimarisi

Bu döküman, UzmanPosta Mail Logger uygulamasının teknik mimarisini, kontrol aşamalarını ve iş akışını açıklamaktadır.

## İçindekiler

- [Genel Bakış](#genel-bakış)
- [Program Akışı](#program-akışı)
- [Validasyon Kontrolleri](#validasyon-kontrolleri)
- [Sınıf Yapısı](#sınıf-yapısı)
- [Dizin Yapısı](#dizin-yapısı)
- [API Entegrasyonu](#api-entegrasyonu)
- [Hata Yönetimi](#hata-yönetimi)

---

## Genel Bakış

UzmanPosta Mail Logger, Uzman Posta API'sinden mail, quarantine ve authentication loglarını çeken, işleyen ve dosyalara kaydeden bir Python uygulamasıdır.

**Temel Özellikler:**
- Çoklu domain ve log tipi desteği (section tabanlı konfigürasyon)
- Paralel veya sıralı çalıştırma
- Position tracking ile kesintisiz log toplama
- Rate limiting ve retry mekanizması
- Lock mekanizması ile çoklu instance koruması

---

## Program Akışı

```
1. Başlatma
   │
   ├── CLI argümanlarını ayrıştır (--config, --section, --all, --parallel, --list)
   ├── Config dosyasını yükle (uzmanposta.ini)
   └── [MailLogger:*] sectionlarını keşfet
   
2. Section Seçimi
   │
   ├── --list → Sectionları listele ve çık
   ├── --section NAME → Belirtilen section'ı çalıştır
   ├── --all → Tüm sectionları çalıştır
   └── (varsayılan) → Otomatik algıla
   
3. Section Çalıştırma (her section için)
   │
   ├── Config validasyonu (API key, start_time)
   ├── Dizinleri oluştur (output, positions, locks)
   ├── Lock al (başka instance kontrolü)
   ├── MailLogger nesnesi oluştur
   └── run() metodunu çağır
   
4. Log Toplama (run metodu)
   │
   ├── Position dosyasını yükle (veya start_time kullan)
   ├── start_time >= end_time kontrolü
   ├── Zaman aralığını chunk'lara böl
   └── Her chunk için:
       │
       ├── API çağrısı yap
       ├── Yanıt başarısız → Retry (exponential backoff)
       ├── Sayfa dolu → Aralığı ikiye böl
       ├── Logları işle ve dosyaya yaz
       └── Position'ı güncelle
   
5. Bitirme
   │
   ├── Metrikleri logla
   ├── Lock'ı bırak
   └── Özet yazdır
```

---

## Validasyon Kontrolleri

| Aşama | Kontrol | Geçerli Değer | Hata Durumu |
|-------|---------|---------------|-------------|
| **Config Yükleme** | API key | Boş olmayan string | `ValueError` - Program durur |
| **Config Yükleme** | API key placeholder | `YOUR_API_KEY_HERE` değil | `ValueError` - Program durur |
| **Config Yükleme** | start_time | >= 0 | `max(0, value)` ile düzeltilir |
| **Lock Alma** | Instance kontrolü | Lock dosyası yok | Section atlanır |
| **Position Okuma** | Dosya erişimi | Okunabilir | `PermissionError` fırlatır |
| **Position Okuma** | Değer formatı | Geçerli integer | `None` döner, config start_time kullanılır |
| **Zaman Kontrolü** | Aralık geçerliliği | start_time < end_time | Log toplama atlanır |
| **API Çağrısı** | HTTP yanıtı | 2xx status | Retry mekanizması devreye girer |
| **API Çağrısı** | JSON formatı | Geçerli JSON | `ValueError` - Retry |

---

## Sınıf Yapısı

### MailLoggerConfig (Dataclass)

Konfigürasyon değerlerini tutan veri sınıfı.

```
MailLoggerConfig
├── api_key: str                    # API anahtarı (zorunlu)
├── log_directory: str              # Log çıktı dizini
├── position_file: str              # Position dosyası yolu
├── url: str                        # API endpoint URL
├── start_time: int = 0             # Başlangıç timestamp'i
├── domain: str = ''                # Domain filtresi
├── log_type: str = 'outgoinglog'   # Log tipi
├── api_category: str = 'mail'      # Kategori (mail/quarantine/authentication)
├── split_interval: int = 300       # Chunk boyutu (saniye)
├── max_time_gap: int = 3600        # Maksimum zaman aralığı
├── verbose: bool = True            # Detaylı çıktı
├── list_retries: int = 10          # Liste API retry sayısı
├── detail_retries: int = 10        # Detay API retry sayısı
├── max_records_per_page: int = 1000 # Sayfa başına maksimum kayıt
├── max_parallel_details: int = 2   # Paralel detay isteği sayısı
└── use_session: bool = True        # HTTP session kullanımı
```

### Metrics (Dataclass)

Çalışma zamanı metriklerini izleyen sınıf.

```
Metrics
├── logs_processed: int = 0         # İşlenen log sayısı
├── errors_count: int = 0           # Hata sayısı
├── api_calls: int = 0              # API çağrı sayısı
├── total_api_time: float = 0.0     # Toplam API süresi
├── min_api_time: float = inf       # Minimum API süresi
├── max_api_time: float = 0.0       # Maksimum API süresi
├── record_api_call(duration)       # API çağrısı kaydet
├── avg_api_time → float            # Ortalama API süresi
├── error_rate → float              # Hata oranı (%)
└── to_dict() → dict                # Metrikleri dict olarak döndür
```

### MailLogger (Ana Sınıf)

Log toplama ve işleme mantığını içeren ana sınıf.

```
MailLogger
├── __init__(config: MailLoggerConfig)
├── run()                           # Ana çalıştırma metodu
├── split_and_retrieve_logs()       # Zaman aralığını böl ve topla
├── retrieve_logs(s, e)             # Belirli aralık için logları al
├── retrieve_detailed_log(id, time) # Detaylı log bilgisi al
├── process_logs(logs)              # Logları dosyaya yaz
├── save_last_position(time)        # Position'ı kaydet
├── load_last_position() → int      # Position'ı yükle
├── acquire_lock(path)              # Lock dosyası al
├── release_lock()                  # Lock dosyasını bırak
├── update_heartbeat(status)        # Heartbeat dosyasını güncelle
├── log_message(msg)                # Mesaj logla
├── log_error(msg)                  # Hata logla
└── close()                         # Session ve kaynakları kapat
```

---

## Dizin Yapısı

### Çıktı Dosyaları

```
output/
├── {domain}/
│   ├── mail/
│   │   ├── incominglog/
│   │   │   └── {domain}_incominglog_YYYY-MM-DD_HH.log
│   │   └── outgoinglog/
│   │       └── {domain}_outgoinglog_YYYY-MM-DD_HH.log
│   │
│   ├── quarantine/
│   │   ├── (type=quarantine durumunda alt dizin yok)
│   │   │   └── {domain}_quarantine_YYYY-MM-DD_HH.log
│   │   └── hold/
│   │       └── {domain}_hold_YYYY-MM-DD_HH.log
│   │
│   └── authentication/
│       └── {domain}_auth_YYYY-MM-DD_HH.log
```

### Yardımcı Dosyalar

```
{script_directory}/
├── positions/
│   └── {section}.pos              # Son işlenen timestamp
│
├── locks/
│   └── {section}.lock             # Instance lock dosyası
│
└── output/{domain}/{category}/
    ├── {section}_heartbeat.json   # Durum ve metrik bilgisi
    ├── messages_YYYY-MM-DD_HH.log # Uygulama mesajları
    └── errors_YYYY-MM-DD_HH.log   # Hata logları
```

---

## API Entegrasyonu

### Endpoint'ler

| Kategori | URL | Açıklama |
|----------|-----|----------|
| mail | `https://yenipanel-api.uzmanposta.com/api/v2/logs/mail` | Gelen/giden mail logları |
| quarantine | `https://yenipanel-api.uzmanposta.com/api/v2/quarantines` | Karantina logları |
| authentication | `https://yenipanel.uzmanposta.com/api/v2/logs/authentication` | Oturum açma logları |

### İstek Parametreleri

| Parametre | Tip | mail | quarantine | authentication |
|-----------|-----|------|------------|----------------|
| `starttime` | int | ✓ | ✓ | ✓ |
| `endtime` | int | ✓ | ✓ | ✓ |
| `type` | string | ✓ | ✓ | ✗ |
| `domain` | string | ✓ (opsiyonel) | ✓ (opsiyonel) | ✓ (opsiyonel) |

### Geçerli Type Değerleri

| Kategori | Type Değerleri |
|----------|----------------|
| mail | `incominglog`, `outgoinglog` |
| quarantine | `quarantine`, `hold` |
| authentication | (type kullanılmaz) |

---

## Hata Yönetimi

### Retry Mekanizması

```
İstek Başarısız
    │
    ├── Attempt 1 → 2s bekle
    ├── Attempt 2 → 4s bekle
    ├── Attempt 3 → 8s bekle
    ├── Attempt 4 → 16s bekle
    ├── Attempt 5 → 32s bekle
    └── Attempt 6+ → 60s bekle (maksimum)
```

**Varsayılan Değerler:**
- `list_retries`: 10 deneme
- `detail_retries`: 10 deneme
- `list_sleep_time`: 2 saniye (başlangıç)
- `detail_sleep_time`: 2 saniye (başlangıç)

### Sayfa Bölme (Splitting)

API `max_records_per_page` (varsayılan: 1000) kadar kayıt döndürürse:

```
Aralık [s, e] → max_records_per_page kadar kayıt
    │
    ├── Orta nokta hesapla: mid = (s + e) / 2
    ├── İki yeni aralık oluştur: [s, mid] ve [mid, e]
    └── Her birini ayrı ayrı işle
```

### Graceful Shutdown

- `Ctrl+C` sinyali yakalanır
- `_shutdown_event` set edilir
- Aktif işlemler tamamlanır
- Lock dosyaları bırakılır
- Özet yazdırılır

---

## Konfigürasyon Örneği

```ini
[DEFAULT]
log_directory = ./output
max_records_per_page = 1000
verbose = True

[MailLogger:example-incoming]
api_key = YOUR_API_KEY_HERE
domain = example.com
category = mail
type = incominglog
start_time = 1703240000

[MailLogger:example-quarantine]
api_key = YOUR_API_KEY_HERE
domain = example.com
category = quarantine
type = quarantine
start_time = 1703240000

[MailLogger:example-auth]
api_key = YOUR_API_KEY_HERE
domain = example.com
category = authentication
start_time = 1703240000
```

---

## CLI Kullanımı

```bash
# Tüm sectionları listele
python uzmanposta.py --list

# Belirli bir section çalıştır
python uzmanposta.py --section MailLogger:example-incoming

# Tüm sectionları sıralı çalıştır
python uzmanposta.py --all

# Tüm sectionları paralel çalıştır (5 worker)
python uzmanposta.py --all --parallel

# Tüm sectionları paralel çalıştır (özel worker sayısı)
python uzmanposta.py --all --parallel --max-workers 3

# Özel config dosyası kullan
python uzmanposta.py --config /path/to/custom.ini --all
```
