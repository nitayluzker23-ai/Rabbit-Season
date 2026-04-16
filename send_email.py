"""
Rabbit Season — Email Sender
Sends the weekly PDF via Gmail SMTP.
Credentials are stored as GitHub Secrets.
"""

import smtplib
import os
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email import encoders
from datetime import datetime, timedelta


def send_pdf(pdf_path: str):
    gmail_user     = os.environ["GMAIL_USER"]
    gmail_password = os.environ["GMAIL_PASSWORD"]
    recipient      = os.environ["RECIPIENT_EMAIL"]

    # Next week Mon–Wed dates for the subject line
    today      = datetime.today()
    monday     = today + timedelta(days=1)
    wednesday  = monday + timedelta(days=2)
    week_str   = f"{monday.strftime('%b %d')}–{wednesday.strftime('%b %d, %Y')}"

    subject = f"Rabbit Season — Week of {week_str}"

    body = f"""
Rabbit Season — Weekly Earnings Volatility Screener

Week covered: {week_str}
Filter: AMC only | Mkt Cap >$20B | Price >$20
Sectors: Technology, Finance, Energy, Biotech/Pharma
Highlights: High-beta names (Beta >1.5) | Avg Historical Move | Market Implied Move

The PDF is attached.

---
Generated automatically every Sunday at 8:00 AM Israel time.
Not financial advice. Options carry significant risk of loss.
    """.strip()

    msg = MIMEMultipart()
    msg["From"]    = gmail_user
    msg["To"]      = recipient
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    filename = f"rabbit_season_{monday.strftime('%Y_%m_%d')}.pdf"
    with open(pdf_path, "rb") as f:
        attachment = MIMEBase("application", "octet-stream")
        attachment.set_payload(f.read())
        encoders.encode_base64(attachment)
        attachment.add_header("Content-Disposition", f"attachment; filename={filename}")
        msg.attach(attachment)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(gmail_user, gmail_password)
        server.sendmail(gmail_user, recipient, msg.as_string())

    print(f"Rabbit Season sent to {recipient}")


if __name__ == "__main__":
    send_pdf("rabbit_season.pdf")
