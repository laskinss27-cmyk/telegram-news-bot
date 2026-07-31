const MODERATION_DATA_URL =
  "https://raw.githubusercontent.com/laskinss27-cmyk/telegram-news-bot/main/data/moderation.json";

const REQUIRED_ENV = [
  "TELEGRAM_BOT_TOKEN",
  "TELEGRAM_CHAT_ID",
  "TELEGRAM_MODERATION_CHAT_ID",
  "TELEGRAM_WEBHOOK_SECRET",
];

function jsonResponse(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
    },
  });
}

function setupPage(message = "") {
  const notice = message
    ? `<p role="status">${message}</p>`
    : "<p>Введите секрет webhook, сохранённый в настройках Worker.</p>";
  return new Response(
    `<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Подключение SHomeNews</title>
  <style>
    body { font: 16px system-ui, sans-serif; max-width: 560px; margin: 64px auto; padding: 0 20px; }
    input, button { box-sizing: border-box; width: 100%; padding: 12px; margin-top: 12px; }
    button { cursor: pointer; }
  </style>
</head>
<body>
  <h1>Подключение Telegram</h1>
  ${notice}
  <form method="post" action="/setup">
    <label>Секрет webhook
      <input type="password" name="setup_key" required autocomplete="off">
    </label>
    <button type="submit">Подключить Telegram</button>
  </form>
</body>
</html>`,
    {
      headers: {
        "content-type": "text/html; charset=utf-8",
        "cache-control": "no-store",
      },
    },
  );
}

export function parseCallbackData(value) {
  if (typeof value !== "string") {
    return null;
  }
  const match = /^(publish|skip):([a-f0-9]{16})$/.exec(value);
  if (!match) {
    return null;
  }
  return { action: match[1], draftId: match[2] };
}

export function findDraft(payload, draftId, messageId) {
  const items = Array.isArray(payload?.items) ? payload.items : [];
  return (
    items.find(
      (item) =>
        item?.id === draftId &&
        Number(item?.review_message_id) === Number(messageId),
    ) ?? null
  );
}

function missingEnvironmentVariables(env) {
  return REQUIRED_ENV.filter((name) => !String(env[name] ?? "").trim());
}

async function telegram(env, method, payload) {
  const response = await fetch(
    `https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/${method}`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
  const result = await response.json().catch(() => null);
  if (!response.ok || !result?.ok) {
    const description = result?.description || `HTTP ${response.status}`;
    throw new Error(`Telegram ${method}: ${description}`);
  }
  return result.result;
}

async function answerCallback(env, callbackId, text, showAlert = false) {
  if (!callbackId) {
    return;
  }
  await telegram(env, "answerCallbackQuery", {
    callback_query_id: callbackId,
    text,
    show_alert: showAlert,
  });
}

async function loadModerationData() {
  const response = await fetch(`${MODERATION_DATA_URL}?v=${Date.now()}`, {
    headers: {
      accept: "application/json",
      "user-agent": "SHomeNewsModerationWorker/1.0",
    },
    cf: { cacheTtl: 0, cacheEverything: false },
  });
  if (!response.ok) {
    throw new Error(`Не удалось загрузить очередь: HTTP ${response.status}`);
  }
  return response.json();
}

async function publishDraft(env, draft) {
  const common = {
    chat_id: env.TELEGRAM_CHAT_ID,
    parse_mode: "HTML",
    disable_notification: false,
  };
  const photoCandidates = [draft.photo_file_id, draft.image_url].filter(Boolean);

  for (const photo of photoCandidates) {
    try {
      return await telegram(env, "sendPhoto", {
        ...common,
        photo,
        caption: String(draft.text ?? ""),
      });
    } catch {
      // Пробуем следующий вариант фото, затем отправку только текста.
    }
  }

  return telegram(env, "sendMessage", {
    ...common,
    text: String(draft.text ?? ""),
    disable_web_page_preview: false,
  });
}

function decisionCacheRequest(draftId) {
  return new Request(`https://shome-news.internal/decisions/${draftId}`);
}

async function readCachedDecision(draftId) {
  const cache = globalThis.caches?.default;
  if (!cache) {
    return null;
  }
  const response = await cache.match(decisionCacheRequest(draftId));
  return response ? response.json().catch(() => null) : null;
}

async function saveCachedDecision(draftId, action) {
  const cache = globalThis.caches?.default;
  if (!cache) {
    return;
  }
  await cache.put(
    decisionCacheRequest(draftId),
    new Response(JSON.stringify({ action }), {
      headers: {
        "content-type": "application/json",
        "cache-control": "public, max-age=2592000",
      },
    }),
  );
}

async function finishReview(env, messageId, resultText) {
  const edit = telegram(env, "editMessageReplyMarkup", {
    chat_id: env.TELEGRAM_MODERATION_CHAT_ID,
    message_id: messageId,
    reply_markup: { inline_keyboard: [] },
  });
  const reply = telegram(env, "sendMessage", {
    chat_id: env.TELEGRAM_MODERATION_CHAT_ID,
    text: resultText,
    reply_to_message_id: messageId,
    allow_sending_without_reply: true,
    disable_notification: true,
  });
  await Promise.allSettled([edit, reply]);
}

async function handleCallbackQuery(env, callback) {
  const message = callback?.message;
  const chatId = String(message?.chat?.id ?? "");
  const messageId = Number(message?.message_id ?? 0);
  const callbackId = String(callback?.id ?? "");
  const parsed = parseCallbackData(callback?.data);

  if (chatId !== String(env.TELEGRAM_MODERATION_CHAT_ID)) {
    await answerCallback(env, callbackId, "Эта кнопка не из группы модерации", true);
    return;
  }
  if (!parsed || !messageId) {
    await answerCallback(env, callbackId, "Неизвестная команда", true);
    return;
  }

  const cached = await readCachedDecision(parsed.draftId);
  if (cached) {
    await answerCallback(env, callbackId, "Уже обработано");
    await finishReview(
      env,
      messageId,
      cached.action === "publish"
        ? "✅ Уже опубликовано в канале"
        : "❌ Уже пропущено",
    );
    return;
  }

  const moderationData = await loadModerationData();
  const draft = findDraft(moderationData, parsed.draftId, messageId);
  if (!draft) {
    await answerCallback(
      env,
      callbackId,
      "Черновик ещё сохраняется. Нажмите снова через несколько секунд.",
      true,
    );
    return;
  }
  if (draft.status !== "pending") {
    const published = draft.status === "published";
    await answerCallback(
      env,
      callbackId,
      published ? "Уже опубликовано" : "Уже обработано",
    );
    await saveCachedDecision(
      parsed.draftId,
      published ? "publish" : "skip",
    ).catch(() => undefined);
    await finishReview(
      env,
      messageId,
      published ? "✅ Уже опубликовано в канале" : "❌ Уже пропущено",
    );
    return;
  }

  if (parsed.action === "publish") {
    await answerCallback(env, callbackId, "Публикую…");
    await publishDraft(env, draft);
    await saveCachedDecision(parsed.draftId, "publish").catch(() => undefined);
    await finishReview(env, messageId, "✅ Опубликовано в канале");
    return;
  }

  await answerCallback(env, callbackId, "Пропускаю…");
  await saveCachedDecision(parsed.draftId, "skip").catch(() => undefined);
  await finishReview(env, messageId, "❌ Пропущено");
}

async function handleTelegramUpdate(env, update) {
  if (!update?.callback_query) {
    return;
  }
  await handleCallbackQuery(env, update.callback_query);
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    if (request.method === "GET" && url.pathname === "/setup") {
      return setupPage();
    }
    if (request.method === "POST" && url.pathname === "/setup") {
      const missing = missingEnvironmentVariables(env);
      if (missing.length) {
        return setupPage(`Не заполнены настройки: ${missing.join(", ")}`);
      }
      const form = await request.formData().catch(() => null);
      if (form?.get("setup_key") !== env.TELEGRAM_WEBHOOK_SECRET) {
        return setupPage("Неверный секрет webhook");
      }
      await telegram(env, "setWebhook", {
        url: `${url.origin}/telegram`,
        secret_token: env.TELEGRAM_WEBHOOK_SECRET,
        allowed_updates: ["callback_query"],
        drop_pending_updates: true,
      });
      return setupPage("✅ Telegram подключён. Теперь кнопки работают сразу.");
    }
    if (request.method === "GET" && url.pathname === "/") {
      return jsonResponse({
        ok: true,
        service: "SHomeNews Telegram moderation",
      });
    }
    if (request.method !== "POST" || url.pathname !== "/telegram") {
      return jsonResponse({ ok: false, error: "Not found" }, 404);
    }

    const missing = missingEnvironmentVariables(env);
    if (missing.length) {
      return jsonResponse(
        { ok: false, error: `Missing configuration: ${missing.join(", ")}` },
        503,
      );
    }

    const secret = request.headers.get("x-telegram-bot-api-secret-token");
    if (secret !== env.TELEGRAM_WEBHOOK_SECRET) {
      return jsonResponse({ ok: false, error: "Unauthorized" }, 401);
    }

    let update;
    try {
      update = await request.json();
    } catch {
      return jsonResponse({ ok: false, error: "Invalid JSON" }, 400);
    }

    ctx.waitUntil(
      handleTelegramUpdate(env, update).catch(async (error) => {
        console.error("Telegram update failed", error);
        const callbackId = String(update?.callback_query?.id ?? "");
        await answerCallback(
          env,
          callbackId,
          "Ошибка обработки. Попробуйте ещё раз.",
          true,
        ).catch(() => undefined);
      }),
    );
    return jsonResponse({ ok: true });
  },
};
