import os
import threading
import requests

TEAMS_WEBHOOK_URL = os.environ.get('TEAMS_WEBHOOK_URL', '')

PRIORITY_COLORS = {
    'urgent': 'FF0000',
    'high': 'FF8C00',
    'normal': '0078D7',
    'low': '808080',
}


def send_teams_notification(title, message, facts=None, color='0078D7'):
    if not TEAMS_WEBHOOK_URL:
        return
    payload = {
        '@type': 'MessageCard',
        '@context': 'http://schema.org/extensions',
        'themeColor': color,
        'summary': title,
        'sections': [{'activityTitle': title, 'text': message}]
    }
    if facts:
        payload['sections'][0]['facts'] = [{'name': k, 'value': str(v)} for k, v in facts.items()]

    def _send():
        try:
            requests.post(TEAMS_WEBHOOK_URL, json=payload, timeout=10)
        except Exception:
            pass

    threading.Thread(target=_send, daemon=True).start()


def notify_brief_assigned(brief_name, sku_count, designer_name, assigned_by, priority='normal', deadline=None):
    color = PRIORITY_COLORS.get(priority, '0078D7')
    facts = {
        'Brief': brief_name,
        'Designer': designer_name,
        'SKU Count': sku_count,
        'Priority': priority.upper(),
        'Assigned By': assigned_by,
    }
    if deadline:
        facts['Deadline'] = deadline
    send_teams_notification(f'Brief Assigned: {brief_name}',
                            f'A new brief has been assigned to **{designer_name}**.', facts, color)


def notify_priority_changed(brief_name, new_priority, changed_by):
    if new_priority != 'urgent':
        return
    send_teams_notification(
        f'URGENT: {brief_name}',
        f'Brief **{brief_name}** has been escalated to **URGENT** by {changed_by}.',
        {'Brief': brief_name, 'New Priority': 'URGENT', 'Changed By': changed_by},
        color='FF0000'
    )
