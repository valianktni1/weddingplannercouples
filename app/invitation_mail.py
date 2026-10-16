"""Approved invitation wording shared by automatic sends and manual previews."""
from datetime import date
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, select_autoescape

_env=Environment(loader=FileSystemLoader(Path(__file__).parent/'templates'),autoescape=select_autoescape(['html']))
FEATURES=['Your checklist and wedding-day timings','Your budget, suppliers and payment dates','Your guest list and family photo groups']


def invitation_email(state,kind,until,trial_days,url,custom=None):
    names=' & '.join(state['names']);trial=kind=='Trial'
    fields={
        'subject':('Your wedding planner trial, ' if trial else 'Your wedding planner is ready, ')+names,
        'heading':'A little help with your wedding plans' if trial else 'A little help with the wedding plans',
        'message':('Hi '+names+',\n\n'+('Here’s your invitation to try the Ivory Digital wedding planner.\n\nIt gives you both one place to organise the plans, keep track of what’s next and enjoy ticking things off together.' if trial else 'Thank you again for booking your wedding with me.\n\nYour Ivory Digital wedding planner is included at no extra cost, giving you both one place to keep the plans together.')),
        'signoff':'Happy planning!\nMark\nWeddings By Mark'}
    if custom is not None:
        if not isinstance(custom,dict) or set(custom)!=set(fields): raise ValueError('Check the invitation subject, heading, message and sign-off.')
        for key,limit in [('subject',250),('heading',180),('message',6000),('signoff',1000)]:
            value=custom[key]
            if not isinstance(value,str) or not value.strip() or len(value)>limit or '\0' in value or (key in ('subject','heading') and any(c in value for c in '\r\n')): raise ValueError('Enter a valid invitation '+key+' within its length limit.')
            fields[key]=value.strip().replace('\r\n','\n').replace('\r','\n')
    setup='Choose your own password to '+('start your free trial.' if trial else 'get started.')+' Once you’re in, you can invite your partner to join your shared planner.'
    cta='Start our free trial' if trial else 'Set up our planner'
    if trial: access=f'Your {trial_days}-day trial starts when you set up your account. No payment is taken.'
    else:
        access='Your planner is available until '+date.fromisoformat(until).strftime('%d %B %Y')
        day=state.get('date','')
        if day and (date.fromisoformat(until)-date.fromisoformat(day)).days==30: access+=' — 30 days after your wedding.'
        else: access+='.'
    footer='This invitation link lasts 7 days. If you need a hand, just reply to this email.'
    html=_env.get_template('emails/invitation.html').render(**fields,paragraphs=fields['message'].split('\n\n'),features=FEATURES,setup=setup,cta=cta,access=access,url=url,footer=footer)
    body='\n\n'.join(['Ivory Digital\nBuilt by Weddings By Mark\nWEDDING PLANNER',fields['heading'],fields['message'],'Make it yours\n'+'\n'.join('• '+x for x in FEATURES),setup,cta+'\n'+url,access,fields['signoff'],footer,'Ivory Digital · Built by Weddings By Mark'])
    return {'email':fields,'subject':fields['subject'],'body':body,'html':html}
