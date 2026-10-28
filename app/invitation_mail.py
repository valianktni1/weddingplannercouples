"""Approved invitation wording shared by automatic sends and manual previews."""
from datetime import date
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, select_autoescape

_env=Environment(loader=FileSystemLoader(Path(__file__).parent/'templates'),autoescape=select_autoescape(['html']))
SENDER_NAME='Mark at Ivory Digital'


def invitation_email(state,kind,until,trial_days,url,custom=None):
    names=' & '.join(state['names']);trial=kind=='Trial'
    fields={
        'subject':('Your wedding planner trial, ' if trial else 'Your wedding planner access, ')+names,
        'heading':'Ivory Digital',
        'message':('Hi '+names+',\n\n'+('Here’s your invitation to try the Ivory Digital wedding planner.\n\nYou can use it to keep your plans, guests, budget and timings together.' if trial else 'Thanks again for booking your wedding with me.\n\nYour Ivory Digital wedding planner is included at no extra cost to help you keep your plans, guests, budget and timings together.')),
        'signoff':'Mark\n'+('Ivory Digital' if trial else 'Weddings By Mark')}
    if custom is not None:
        if not isinstance(custom,dict) or set(custom)!=set(fields): raise ValueError('Check the invitation subject, heading, message and sign-off.')
        for key,limit in [('subject',250),('heading',180),('message',6000),('signoff',1000)]:
            value=custom[key]
            if not isinstance(value,str) or not value.strip() or len(value)>limit or '\0' in value or (key in ('subject','heading') and any(c in value for c in '\r\n')): raise ValueError('Enter a valid invitation '+key+' within its length limit.')
            fields[key]=value.strip().replace('\r\n','\n').replace('\r','\n')
    setup='Use the link below to choose your password and '+('start your trial.' if trial else 'get started.')
    cta='Start our free trial' if trial else 'Set up our planner'
    if trial: access=f'Your {trial_days}-day trial starts when you set up your account. No payment is taken.'
    else:
        access='Your planner is available until '+date.fromisoformat(until).strftime('%d %B %Y')
        day=state.get('date','')
        if day and (date.fromisoformat(until)-date.fromisoformat(day)).days==30: access+=' — 30 days after your wedding.'
        else: access+='.'
    expiry='Your setup link is valid for 7 days.'
    help_text='If you need a hand, just reply to this email and I’ll help.'
    reason=('This invitation gives you access to a trial of the Ivory Digital wedding planner.' if trial else 'This invitation was sent because you booked your wedding with Weddings By Mark.')
    html=_env.get_template('emails/invitation.html').render(**fields,paragraphs=fields['message'].split('\n\n'),setup=setup,cta=cta,access=access,url=url,expiry=expiry,help_text=help_text,reason=reason)
    body='\n\n'.join([fields['heading'],fields['message'],setup,cta+'\n'+url,expiry,access,help_text,fields['signoff'],'Ivory Digital Wedding Planner · Built by Weddings By Mark',reason])
    return {'email':fields,'subject':fields['subject'],'body':body,'html':html}
