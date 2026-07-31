# Мгновенная модерация в Cloudflare

Worker принимает от Telegram только нажатия кнопок из группы модерации.
При выборе «Опубликовать» он берёт сохранённый черновик из
`data/moderation.json` и сразу отправляет его в канал. При выборе
«Пропустить» кнопки удаляются без публикации.

## Настройки Cloudflare

Проект разворачивается из корня репозитория:

- имя проекта: `shome-news-moderation`;
- build command: оставить пустым;
- deploy command: `npx wrangler deploy`.

После первого развёртывания в `Settings → Variables and Secrets` нужно
добавить четыре зашифрованных секрета:

- `TELEGRAM_BOT_TOKEN`;
- `TELEGRAM_CHAT_ID`;
- `TELEGRAM_MODERATION_CHAT_ID`;
- `TELEGRAM_WEBHOOK_SECRET`.

Затем Telegram webhook направляется на адрес созданного Worker с передачей
того же `TELEGRAM_WEBHOOK_SECRET`. Для этого нужно открыть страницу
`https://shome-news-moderation.<ваш-поддомен>.workers.dev/setup`, ввести
секрет webhook и нажать «Подключить Telegram».

Пока webhook не подключён, сбор новостей на GitHub продолжает работать,
но новые кнопки не обрабатываются.
