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
- `JWT_SECRET` → дълъг случаен низ (например от `openssl rand -hex 32`)

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
