import cors from "cors";
import "dotenv/config";
import express from "express";
import nodemailer from "nodemailer";

const app = express();
const port = Number(process.env.PORT || 8787);

app.use(cors());
app.use(express.json({ limit: "128kb" }));

function requireEnv(name) {
  const value = process.env[name]?.trim();
  if (!value) {
    throw new Error(`${name} is required`);
  }
  return value;
}

function smtpPassword() {
  return requireEnv("SMTP_PASS").replace(/\s/g, "");
}

function createTransporter() {
  return nodemailer.createTransport({
    host: requireEnv("SMTP_HOST"),
    port: Number(process.env.SMTP_PORT || 587),
    secure: String(process.env.SMTP_SECURE || "false").toLowerCase() === "true",
    auth: {
      user: requireEnv("SMTP_USER"),
      pass: smtpPassword(),
    },
  });
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function smtpError(error) {
  if (error?.responseCode === 535) {
    return {
      status: 401,
      body: {
        error: "Gmail rejected the SMTP login. Create a fresh Gmail app password and update SMTP_PASS.",
        code: error.code,
        responseCode: error.responseCode,
      },
    };
  }

  return {
    status: 500,
    body: {
      error: error.message,
      code: error.code,
      responseCode: error.responseCode,
    },
  };
}

app.get("/health", (_req, res) => {
  res.json({ status: "ok", service: "notification-gateway" });
});

app.get("/verify-smtp", async (_req, res) => {
  try {
    const transporter = createTransporter();
    await transporter.verify();
    return res.json({ status: "ok", smtpUser: requireEnv("SMTP_USER") });
  } catch (error) {
    const { status, body } = smtpError(error);
    return res.status(status).json(body);
  }
});

app.post("/send-email", async (req, res) => {
  const { to, title, message } = req.body || {};
  if (!to || !title || !message) {
    return res.status(400).json({ error: "to, title and message are required" });
  }

  try {
    const transporter = createTransporter();
    const info = await transporter.sendMail({
      from: process.env.SMTP_FROM?.trim() || requireEnv("SMTP_USER"),
      to,
      subject: title,
      text: message,
      html: `<p>${escapeHtml(message).replace(/\n/g, "<br />")}</p>`,
    });
    return res.json({ status: "sent", messageId: info.messageId });
  } catch (error) {
    const { status, body } = smtpError(error);
    return res.status(status).json(body);
  }
});

app.listen(port, () => {
  console.log(`Notification gateway listening on http://127.0.0.1:${port}`);
});
