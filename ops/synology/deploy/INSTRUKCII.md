# BEG_Work на Synology DS923+ — инструкции

## Какво ще стане

Приложението ще работи на твоя Synology, а данните остават в MongoDB Atlas.
Emergent не участва.

```
Браузър → Synology (порт 8080) → nginx → React
                                    ↓
                                 backend → Atlas
```

---

## Стъпка 1 — Включи SSH на Synology

DSM → Control Panel → Terminal & SNMP → отметни "Enable SSH service" → Apply

Запомни порта (по подразбиране 22).

---

## Стъпка 2 — Създай папката

DSM → File Station → в споделената папка `docker` създай нова папка `begwork`.

Ако папка `docker` няма, създай я: Control Panel → Shared Folder → Create.

---

## Стъпка 3 — Качи файловете

Качи в `/docker/begwork` (през File Station, влачене с мишката):

- `Dockerfile.backend`
- `Dockerfile.frontend`
- `nginx.conf`
- `docker-compose.yml`
- `.env.example`

---

## Стъпка 4 — Свържи се по SSH

От Windows отвори командния ред и напиши:

```
ssh Panko@192.168.1.112
```

(замени `Panko` с твоето потребителско име в DSM, ако е различно)

Въведи паролата. Няма да се вижда, докато пишеш — това е нормално.

---

## Стъпка 5 — Влез в папката и вземи кода

```
cd /volume1/docker/begwork
sudo git clone https://github.com/krumingo/BEG_Worck.git repo
```

Ако `git` липсва, инсталирай Git Server от Package Center.

---

## Стъпка 6 — Настрой .env

```
sudo cp .env.example .env
sudo vi .env
```

Във `vi`: натисни `i` за редактиране, промени:

- `PAROLA` → истинската парола от Atlas
- `JWT_SECRET` → дълъг случаен низ (например от `openssl rand -hex 32`). **Поне 32 знака** — без него или с по-къс сървърът **не стартира** (SEC-03).

По желание (SEC-03 / Р76) — без тях програмата работи, само AI е изключен:

- `ANTHROPIC_API_KEY` → ключът на фирмата за Anthropic (Claude). Само тук, никога в кода.
- `ANTHROPIC_MODEL` → името на модела, което Крум е избрал. Без ключ или модел AI отговаря „AI не е настроен“, а ръчната работа продължава.
- AI се включва за фирмата отделно (флаг `ai_enabled`, Platform Admin) — по подразбиране е изключен.
- `INTERNAL_JOB_KEY` → само ако външна услуга ще пуска напомнянията през `/api/internal/run-reminder-jobs` (поне 32 знака). Вграденото пускане на всеки 15 минути не се нуждае от него.

После натисни `Esc`, напиши `:wq` и Enter за запис.

---

## Стъпка 7 — Пусни

```
sudo docker-compose up -d --build
```

Първият път отнема 10–20 минути (сваля и компилира всичко).

---

## Стъпка 8 — Провери

```
sudo docker-compose ps
sudo docker-compose logs backend --tail 50
```

После отвори в браузъра:

```
http://192.168.1.112:8080
```

Влез с `Krum@begfull.bg` и паролата си.

---

## Полезни команди

```
sudo docker-compose logs -f backend      # виж какво става
sudo docker-compose restart              # рестарт
sudo docker-compose down                 # спри всичко
sudo docker-compose up -d --build        # пусни наново след промяна
```

## Обновяване на кода после

> **Остаряло (W0-09A):** `repo/` в production не е git checkout, затова `git pull` не работи.
> Обновяване и rollback — само по `ops/release/README.md` (exact-version bundle, precheck, smoke, auto-rollback).

```
cd /volume1/docker/begwork/repo
sudo git pull
cd ..
sudo docker-compose up -d --build
```

---

## Достъп отвън (по-късно)

За да работи от телефона извън дома:

1. DSM → Control Panel → External Access → рутерът да пренасочва порт 8080
2. Или по-добре: Reverse Proxy в DSM (Login Portal → Advanced → Reverse Proxy)
   с истински SSL сертификат от Let's Encrypt

Това го правим след като локално всичко работи.
