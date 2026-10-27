import json
import os
import smtplib
import urllib.error
import urllib.request
from email.message import EmailMessage
from typing import Any, Dict, List, Optional


RISK_ORDER = {"high": 3, "medium": 2, "low": 1}


class Notifier:
    def __init__(
        self,
        webhook_url: str = "",
        webhook_type: str = "generic",
        min_risk: str = "medium",
        timeout: int = 10,
        smtp_host: str = "",
        smtp_port: int = 465,
        smtp_user: str = "",
        smtp_password: str = "",
        smtp_from: str = "",
        smtp_to: Optional[List[str]] = None,
        smtp_ssl: bool = True,
    ) -> None:
        self.webhook_url = webhook_url.strip()
        self.webhook_type = webhook_type.strip().lower() or "generic"
        self.min_risk = min_risk if min_risk in RISK_ORDER else "medium"
        self.timeout = max(3, timeout)
        self.smtp_host = smtp_host.strip()
        self.smtp_port = max(1, smtp_port)
        self.smtp_user = smtp_user.strip()
        self.smtp_password = smtp_password
        self.smtp_from = smtp_from.strip()
        self.smtp_to = [value.strip() for value in (smtp_to or []) if value.strip()]
        self.smtp_ssl = smtp_ssl

    @classmethod
    def from_env(cls) -> "Notifier":
        recipients = [
            value.strip()
            for value in os.getenv("MONITOR_ALERT_EMAIL_TO", "").split(",")
            if value.strip()
        ]
        return cls(
            webhook_url=os.getenv("MONITOR_ALERT_WEBHOOK_URL", ""),
            webhook_type=os.getenv("MONITOR_ALERT_WEBHOOK_TYPE", "generic"),
            min_risk=os.getenv("MONITOR_ALERT_MIN_RISK", "medium").lower(),
            timeout=int(os.getenv("MONITOR_ALERT_TIMEOUT", "10")),
            smtp_host=os.getenv("MONITOR_SMTP_HOST", ""),
            smtp_port=int(os.getenv("MONITOR_SMTP_PORT", "465")),
            smtp_user=os.getenv("MONITOR_SMTP_USER", ""),
            smtp_password=os.getenv("MONITOR_SMTP_PASSWORD", ""),
            smtp_from=os.getenv("MONITOR_SMTP_FROM", ""),
            smtp_to=recipients,
            smtp_ssl=os.getenv("MONITOR_SMTP_SSL", "true").lower()
            not in {"0", "false", "no"},
        )

    @property
    def webhook_enabled(self) -> bool:
        return bool(self.webhook_url)

    @property
    def email_enabled(self) -> bool:
        return bool(self.smtp_host and self.smtp_from and self.smtp_to)

    @property
    def enabled(self) -> bool:
        return self.webhook_enabled or self.email_enabled

    def public_status(self) -> Dict[str, Any]:
        channels = []
        if self.webhook_enabled:
            channels.append("webhook")
        if self.email_enabled:
            channels.append("email")
        return {
            "enabled": self.enabled,
            "channels": channels,
            "webhook_type": self.webhook_type if self.webhook_enabled else "",
            "min_risk": self.min_risk,
        }

    def notify(
        self,
        alerts: List[Dict[str, Any]],
        run_id: str,
        coverage_note: str = "",
    ) -> Dict[str, Any]:
        eligible = [
            alert
            for alert in alerts
            if RISK_ORDER.get(str(alert.get("risk_level", "low")), 0)
            >= RISK_ORDER[self.min_risk]
        ][:10]
        if not eligible:
            return {
                "enabled": self.enabled,
                "attempted": 0,
                "sent": 0,
                "errors": [],
                "status": "no_eligible_alerts",
            }

        text = self._build_text(eligible, run_id, coverage_note)
        errors = []
        sent = 0
        if self.webhook_enabled:
            try:
                self._send_webhook(eligible, run_id, coverage_note, text)
                sent += 1
            except Exception as exc:
                errors.append(f"webhook: {type(exc).__name__}: {exc}"[:500])
        if self.email_enabled:
            try:
                self._send_email(text)
                sent += 1
            except Exception as exc:
                errors.append(f"email: {type(exc).__name__}: {exc}"[:500])
        return {
            "enabled": self.enabled,
            "attempted": len(eligible),
            "sent": sent,
            "errors": errors,
            "status": "sent" if sent else "failed" if errors else "not_configured",
            "eligible_item_ids": [alert.get("item_id") for alert in eligible],
        }

    def _build_text(
        self, alerts: List[Dict[str, Any]], run_id: str, coverage_note: str
    ) -> str:
        lines = [
            f"【舆情预警】发现 {len(alerts)} 条命中信号",
            f"运行编号：{run_id}",
            "",
        ]
        for index, alert in enumerate(alerts, start=1):
            level = {"high": "高风险", "medium": "中风险", "low": "低风险"}.get(
                alert.get("risk_level", "low"), "低风险"
            )
            lines.extend(
                [
                    f"{index}. [{level}] {alert.get('title', '')}",
                    f"来源：{alert.get('source', '')}",
                    f"命中词：{'、'.join(alert.get('matched_terms') or []) or '未记录'}",
                    f"链接：{alert.get('url', '')}",
                    "理由：" + ("；".join(alert.get("risk_reasons") or []) or "未记录"),
                    "",
                ]
            )
        if coverage_note:
            lines.extend(["覆盖说明：" + coverage_note, ""])
        lines.append("该预警由规则与可选模型辅助生成，请人工核查原始证据。")
        return "\n".join(lines)

    def _send_webhook(
        self,
        alerts: List[Dict[str, Any]],
        run_id: str,
        coverage_note: str,
        text: str,
    ) -> None:
        if self.webhook_type == "wecom":
            payload = {"msgtype": "markdown", "markdown": {"content": text}}
        elif self.webhook_type == "feishu":
            payload = {"msg_type": "text", "content": {"text": text}}
        else:
            payload = {
                "event": "public_opinion_alert",
                "run_id": run_id,
                "coverage_note": coverage_note,
                "alerts": alerts,
                "text": text,
            }
        request = urllib.request.Request(
            self.webhook_url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                if response.status >= 400:
                    raise RuntimeError(f"webhook HTTP {response.status}")
        except urllib.error.URLError as exc:
            raise RuntimeError(str(exc)) from exc

    def _send_email(self, text: str) -> None:
        message = EmailMessage()
        message["Subject"] = "【舆情预警】监测发现新的风险信号"
        message["From"] = self.smtp_from
        message["To"] = ", ".join(self.smtp_to)
        message.set_content(text)
        if self.smtp_ssl:
            with smtplib.SMTP_SSL(
                self.smtp_host, self.smtp_port, timeout=self.timeout
            ) as smtp:
                if self.smtp_user:
                    smtp.login(self.smtp_user, self.smtp_password)
                smtp.send_message(message)
        else:
            with smtplib.SMTP(
                self.smtp_host, self.smtp_port, timeout=self.timeout
            ) as smtp:
                smtp.ehlo()
                if smtp.has_extn("starttls"):
                    smtp.starttls()
                    smtp.ehlo()
                if self.smtp_user:
                    smtp.login(self.smtp_user, self.smtp_password)
                smtp.send_message(message)
