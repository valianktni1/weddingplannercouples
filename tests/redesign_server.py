# Disposable local-only sample installation for the redesign browser checks.
# It never opens an existing data directory and blocks all outbound SMTP.
import sys,tempfile,json,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app import create_app
from app.core import connect,empty_state,cipher
from werkzeug.security import generate_password_hash
root=Path(tempfile.mkdtemp(prefix='ivory-design-'))
a=create_app({'DATA_DIR':str(root/'data'),'BACKUP_DIR':str(root/'backups'),'SECURE_COOKIES':False,'APP_URL':'http://127.0.0.1:8765'})
db=connect(a.config['DATABASE']);s=empty_state();s.update(email='test@example.com',ready=True,names=['Emma','Jamie'],date='2027-06-19',budget=18000)
s['day']['venue']='Example Hall';s['priorities']=['Time with guests','Relaxed photographs']
s['suppliers']=[{'id':'venue','name':'Example Hall','category':'Venue','total':12000,'booked':True,'contact':'venue@example.com','finish':None},{'id':'photo','name':'Test Photographer','category':'Photo + video','total':800,'booked':True,'contact':'photo@example.com','finish':1320}]
s['payments']=[{'id':'venue-balance','supplier':'venue','title':'Balance','amount':12000,'paid':5400,'due':'2026-11-02','paidDate':'2026-10-01'}]
s['tasks']=[{'id':'confirm','title':'Confirm our ceremony time','owner':'Together','due':'2026-11-04','done':False},{'id':'music','title':'Choose our first dance','owner':'Together','due':'','done':False}]
s['events']=[{'id':'florist','title':'Meet your florist','date':'2026-11-09','kind':'Appointment','done':False}]
s['guests']=[{'id':'g1','name':'Pat','household':'','attendance':'Day','rsvp':'Accepted','meal':'','diet':'','access':'','table':''},{'id':'g2','name':'Robin','household':'','attendance':'Day','rsvp':'Waiting','meal':'','diet':'','access':'','table':''}]
for uid,email,state in [('test','test@example.com',s),('new','new@example.com',empty_state())]:
 db.execute('INSERT INTO users(id,email,password,verified,created) VALUES(?,?,?,1,?)',(uid,email,generate_password_hash('test-only-long-password'),time.time()))
 db.execute('INSERT INTO weddings(id,state,access_until,created) VALUES(?,?,?,?)',(uid,json.dumps(state),'2030-01-01',time.time()));db.execute('INSERT INTO members VALUES(?,?)',(uid,uid))
db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',('wbm_booking_enabled','true'))
db.execute('INSERT INTO wbm_timing_links VALUES(?,?,?,?,?,?,?)',('00000000-0000-0000-0000-000000000001','test','test@example.com','2027-06-19',json.dumps({'revision':'design-qa','fields':[{'key':'day_contact','label':'Contact on the day','enabled':True,'step':3,'kind':'builtin'}]}),time.time(),time.time()))
secret=cipher(a.config['SECRET_VALUE']).encrypt(b'JBSWY3DPEHPK3PXP').decode()
db.execute('INSERT INTO users(id,email,password,role,verified,totp,created) VALUES("admin","admin@example.com",?,"admin",1,?,?)',(generate_password_hash('test-only-long-password'),secret,time.time()));db.commit();db.close()
# Any accidental attempt to use real SMTP in this isolated design check must fail.
import app.mail_service as mail_service
class NoSMTP:
 def __init__(self,*args,**kwargs):raise RuntimeError('No external mail allowed in design QA')
mail_service.smtplib.SMTP=NoSMTP;mail_service.smtplib.SMTP_SSL=NoSMTP
a.run(host='127.0.0.1',port=8765,use_reloader=False)
