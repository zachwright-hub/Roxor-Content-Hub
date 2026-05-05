import smtplib
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart


def send_invite(to_email, setup_url, invited_by_name):
    host     = os.environ.get('SMTP_HOST', '')
    port     = int(os.environ.get('SMTP_PORT', 587))
    user     = os.environ.get('SMTP_USER', '')
    password = os.environ.get('SMTP_PASSWORD', '')
    from_addr = os.environ.get('SMTP_FROM', user)

    if not all([host, user, password]):
        raise RuntimeError('SMTP not configured — set SMTP_HOST, SMTP_USER, SMTP_PASSWORD in .env')

    msg = MIMEMultipart('alternative')
    msg['Subject'] = "You've been invited to Roxor Content HUB"
    msg['From']    = from_addr
    msg['To']      = to_email

    text = f"""Hi,

{invited_by_name} has invited you to join Roxor Content HUB.

Set up your account here:
{setup_url}

This link expires in 7 days.

— Roxor Content HUB
"""

    html = f"""<!DOCTYPE html>
<html>
<body style="font-family:Inter,Segoe UI,sans-serif;background:#0a0f2e;margin:0;padding:48px 16px;">
  <div style="max-width:520px;margin:0 auto;border-radius:12px;overflow:hidden;border:1px solid rgba(242,196,0,0.2);">
    <div style="background:#010336;padding:28px 32px;border-bottom:1px solid rgba(242,196,0,0.2);text-align:center;">
      <span style="font-size:10px;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:#F2C400;display:block;margin-bottom:4px;">ROXOR GROUP</span>
      <span style="font-size:20px;font-weight:800;color:#e8eaf0;">Content HUB</span>
    </div>
    <div style="background:#0e1445;padding:40px 32px;">
      <p style="color:#cdd4f0;margin:0 0 16px;">Hi there,</p>
      <p style="color:#cdd4f0;margin:0 0 28px;">
        <strong style="color:#ffffff;">{invited_by_name}</strong> has invited you to
        <strong style="color:#F2C400;">Roxor Content HUB</strong> — the central hub for all content tools.
      </p>
      <div style="text-align:center;margin:36px 0;">
        <a href="{setup_url}"
           style="display:inline-block;background:#F2C400;color:#010336;font-weight:700;
                  padding:14px 36px;border-radius:8px;text-decoration:none;font-size:15px;">
          Set Up My Account
        </a>
      </div>
      <p style="color:#8892b0;font-size:12px;margin:0 0 6px;">Or paste this link into your browser:</p>
      <p style="color:#8892b0;font-size:12px;word-break:break-all;background:rgba(255,255,255,0.05);
                padding:10px 14px;border-radius:6px;margin:0 0 28px;">{setup_url}</p>
      <p style="color:#5a6280;font-size:12px;margin:0;border-top:1px solid rgba(255,255,255,0.06);padding-top:20px;">
        This link expires in 7 days. If you weren't expecting this, ignore it.
      </p>
    </div>
  </div>
</body>
</html>"""

    msg.attach(MIMEText(text, 'plain'))
    msg.attach(MIMEText(html, 'html'))

    with smtplib.SMTP(host, port) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.login(user, password)
        smtp.sendmail(from_addr, to_email, msg.as_string())
