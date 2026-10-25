"""Private wedding stationery drafts and deterministic PDF/PNG layouts.

Artwork is local, fonts are embedded, and no external AI/service is called at runtime.
"""
import io
from functools import lru_cache
import json
import math
import re
import threading
import time
from datetime import date
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageOps
from flask import abort, jsonify, render_template, request, send_file
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.colors import HexColor
from reportlab.lib.utils import ImageReader
from .core import digest

SCHEMA='''CREATE TABLE IF NOT EXISTS stationery_drafts(
 wedding_id TEXT NOT NULL,kind TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 0,
 data TEXT NOT NULL,source_hash TEXT NOT NULL,updated REAL NOT NULL,
 exported_source TEXT,exported_revision INTEGER,exported_at REAL,
 PRIMARY KEY(wedding_id,kind),FOREIGN KEY(wedding_id) REFERENCES weddings(id) ON DELETE CASCADE);'''
ASSETS=Path(__file__).parent/'static'/'stationery'
MM=72/25.4
COLLECTIONS={
 'editorial':{'name':'Modern Editorial','description':'Bold names, clean space and a fine accent.','palettes':{'burgundy':['#fffaf2','#241e1c','#763034'],'forest':['#fffaf2','#203b32','#52664a'],'ink':['#fffdf7','#242424','#5d5d5d']}},
 'botanical':{'name':'Botanical Garden','description':'Delicate greenery on warm ivory.','palettes':{'sage':['#fffcf5','#203b32','#60734c'],'forest':['#fffaf2','#153c32','#567464'],'olive':['#fffdf5','#343d28','#72754a']}},
 'classic':{'name':'Timeless Classic','description':'Fine borders, balanced lettering and your initials.','palettes':{'navy':['#fffdf5','#182e48','#182e48'],'forest':['#fffdf5','#203e32','#203e32'],'burgundy':['#fffdf5','#612f36','#612f36']}},
 'meadow':{'name':'Romantic Meadow','description':'Soft wildflowers and airy lettering.','palettes':{'rose':['#fffdf6','#353c2d','#9d575e'],'blue':['#fffdf6','#263d55','#536a83'],'sage':['#fffdf6','#263d32','#5e754f']}},
 'colour':{'name':'Contemporary Colour','description':'Playful printed borders and confident colour.','palettes':{'berry':['#fff8ec','#6a1e2a','#c87886'],'blue':['#fffbed','#244a6b','#88a8bc'],'green':['#fffbed','#28533c','#a6b58c']}},
 'photo':{'name':'Photo Story','description':'Your photograph with considered, simple lettering.','palettes':{'neutral':['#fffdf6','#292925','#766957'],'navy':['#fffdf6','#243c53','#708393'],'forest':['#fffdf6','#263f32','#78836c']}}
}
KINDS={
 'day':{'name':'Day invitation','sizes':['5x7','A5']},
 'evening':{'name':'Evening invitation','sizes':['5x7','A5']},
 'save_date':{'name':'Save the date','sizes':['A6','5x7']},
 'welcome':{'name':'Welcome sign','sizes':['A2','A1','A3']},
 'menu':{'name':'Menu','sizes':['DL','A5']},
 'place':{'name':'Place cards','sizes':['place','folded']},
 'table':{'name':'Table names / numbers','sizes':['A6','A5']},
 'seating':{'name':'Seating chart','sizes':['A2','A1','A3']},
 'thanks':{'name':'Thank-you card','sizes':['A6','5x7']}
}
SIZES={'5x7':(127,177.8),'A5':(148,210),'A6':(105,148),'A3':(297,420),'A2':(420,594),'A1':(594,841),'DL':(99,210),'place':(90,50),'folded':(90,100)}
LABELS={'place':'90 × 50 mm · flat','folded':'90 × 100 mm · fold to 90 × 50','5x7':'5 × 7 in','DL':'99 × 210 mm'}
FONT_LOCK=threading.Lock()
RENDER_LOCK=threading.BoundedSemaphore(2)


def fonts():
    with FONT_LOCK:
        for name,file in [('StationerySerif','CormorantGaramond-Regular.ttf'),('StationeryItalic','CormorantGaramond-Italic.ttf'),('StationerySans','Outfit-Regular.ttf')]:
            if name not in pdfmetrics.getRegisteredFontNames():pdfmetrics.registerFont(TTFont(name,str(ASSETS/'fonts'/file)))


def source(state,kind):
    relevant={'names':state['names'],'date':state['date']}
    if kind in ('day','evening','save_date'):relevant['venue']=state['day']['venue']
    if kind=='evening':relevant['reception']=state['day'].get('receptionVenue','')
    if kind in ('place','table','seating'):relevant['guests']=[{k:g.get(k,'') for k in ('id','name','table','rsvp')} for g in state['guests']]
    return digest(json.dumps(relevant,sort_keys=True,ensure_ascii=False))


def defaults(state,kind):
    return {'collection':'botanical','palette':'sage','size':KINDS[kind]['sizes'][0],
            'names':' & '.join(n for n in state['names'] if n),'date':state['date'],
            'venue':(state['day'].get('receptionVenue') or state['day']['venue']) if kind=='evening' else state['day']['venue'] if kind in ('day','save_date') else '',
            'intro':'Together with their families','message':'invite you to celebrate their wedding' if kind=='day' else 'invite you to their evening celebration' if kind=='evening' else 'Please save the date' if kind=='save_date' else 'Thank you for being part of our day.' if kind=='thanks' else '',
            'arrival':'','closing':'Reception and celebrations to follow' if kind=='day' else '',
            'recipient':'','menu':'',
            'photo':'','photo_mode':'colour','photo_focus':'centre','photo_x':'50','photo_y':'50','photo_zoom':'1','guest_scope':'accepted','guest_id':'','table_name':''}


def validate(value,kind):
    if not isinstance(value,dict):raise ValueError('Choose your stationery details.')
    allowed={'collection':24,'palette':24,'size':16,'names':220,'date':10,'venue':180,'intro':160,'message':500,'arrival':160,'closing':240,'recipient':160,'menu':1800,'photo':64,'photo_mode':16,'photo_focus':16,'guest_scope':20,'guest_id':64,'table_name':100}
    crop_fields={'photo_x','photo_y','photo_zoom'}
    if set(value)-crop_fields!=set(allowed):raise ValueError('Reload the stationery page to use the current fields.')
    result={}
    for key,limit in allowed.items():
        v=value[key]
        if not isinstance(v,str) or len(v)>limit or any(ord(c)<32 and c not in '\n\t' for c in v):raise ValueError('Check '+key.replace('_',' ')+'.')
        result[key]=v.strip()
    c=COLLECTIONS.get(result['collection'])
    if not c or result['palette'] not in c['palettes']:raise ValueError('Choose a collection and one of its colours.')
    if result['size'] not in KINDS[kind]['sizes']:raise ValueError('Choose a suitable paper size.')
    if result['date']:
        try:date.fromisoformat(result['date'])
        except ValueError:raise ValueError('Check the wedding date.')
    if result['guest_scope'] not in ('accepted','invited') or result['photo_mode'] not in ('colour','mono') or result['photo_focus'] not in ('centre','top','bottom'):raise ValueError('Check guest and photo choices.')
    # Older clients and saved drafts keep their original top/centre/bottom framing.
    for key,default,low,high in [('photo_x','50',0,100),('photo_y',{'top':'0','centre':'50','bottom':'100'}[result['photo_focus']],0,100),('photo_zoom','1',1,3)]:
        v=value.get(key,default)
        try:
            if not isinstance(v,str) or len(v)>16:raise ValueError()
            number=float(v)
            if not math.isfinite(number) or not low<=number<=high:raise ValueError()
        except (TypeError,ValueError):raise ValueError('Check photograph position and zoom.')
        result[key]=str(number)
    return result


def crop_photo(photo,target,config):
    """Use the same cover crop geometry for preview, PNG and print PDF."""
    x=float(config.get('photo_x',50))/100
    y=float(config.get('photo_y',{'top':0,'centre':50,'bottom':100}[config['photo_focus']]))/100
    zoom=float(config.get('photo_zoom',1))
    ratio=target[0]/target[1]
    cw=min(photo.width,photo.height*ratio)/zoom
    ch=cw/ratio
    left=(photo.width-cw)*x;top=(photo.height-ch)*y
    return photo.resize(target,Image.Resampling.LANCZOS,box=(left,top,left+cw,top+ch))


def selected_guests(state,config):
    return [g for g in state['guests'] if g['rsvp']=='Accepted' or config['guest_scope']=='invited' and g['rsvp']!='Declined']


def readable_date(value):
    if not value:return 'Wedding date to confirm'
    d=date.fromisoformat(value)
    return f'{d.strftime("%A")} {d.day} {d.strftime("%B %Y")}'


@lru_cache(maxsize=4)
def artwork(name,transform='none'):
    if name=='meadow-sprig':
        base=artwork('meadow');part=base.crop((int(base.width*.70),0,base.width,base.height));return part.crop(part.getbbox())
    image=Image.open(ASSETS/'art'/(name+'.webp')).convert('RGBA')
    if transform=='rotate':return image.transpose(Image.Transpose.ROTATE_180)
    if transform=='top':return image.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    if transform=='flip':return image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    return image


class Layout:
    """One display list shared by preview, PNG and vector PDF output."""
    def __init__(self,width,height,config,kind):
        fonts();self.w=width;self.h=height;self.ops=[];self.issues=[];self.config=config;self.kind=kind
        self.bg,self.ink,self.accent=COLLECTIONS[config['collection']]['palettes'][config['palette']]
        self.rect(0,0,width,height,self.bg)
        self.offset=height/2 if kind=='place' and config['size']=='folded' else 0
        self.area=height-self.offset
    def rect(self,x,y,w,h,fill,stroke=None,line=.6):self.ops.append(('rect',x,y,w,h,fill,stroke,line))
    def line(self,x,y,xx,yy,col,width=.5):self.ops.append(('line',x,y,xx,yy,col,width))
    def image(self,image,x,y,w,h):self.ops.append(('image',image,x,y,w,h))
    def text(self,text,x,y,width,height,size,minsize=None,font='StationerySerif',align='center',colour=None):
        if not text:return
        face=pdfmetrics.getFont(font).face
        unsupported=[c for c in text if not c.isspace() and ord(c) not in face.charToGlyph]
        if unsupported:self.issues.append('This design cannot print one of the characters in your text. Please use a supported spelling.');return
        def wrap(size):
            lines=[]
            for para in text.split('\n'):
                if not para.strip():lines.append('');continue
                line=''
                for word in para.split():
                    if pdfmetrics.stringWidth(word,font,size)>width:return None
                    test=(line+' '+word).strip()
                    if line and pdfmetrics.stringWidth(test,font,size)>width:lines.append(line);line=word
                    else:line=test
                lines.append(line)
            return lines
        minimum=minsize if minsize is not None else size*.72
        while size>=minimum-.01:
            lines=wrap(size)
            if lines is not None and len(lines)*size*1.2<=height:break
            size-=.5
        else:self.issues.append('Some wording is too long for this layout. Shorten it or choose a larger size.');return
        for i,line in enumerate(lines):
            tx=x if align=='left' else x+width/2-pdfmetrics.stringWidth(line,font,size)/2
            self.ops.append(('text',line,tx,y+size+i*size*1.2,size,font,colour or self.ink))
    def names(self,text,top,high,style='inline',align='center'):
        """Fit the couple as one composition, keeping the ampersand in the accent colour."""
        parts=re.split(r'\s+(?:&|and)\s+',text,maxsplit=1,flags=re.I)
        if len(parts)==2:
            lines=parts if style=='editorial' else [parts[0]+' &',parts[1]] if style=='colour' else [parts[0],'&',parts[1]] if style=='meadow' else [text]
            if style=='editorial':lines=[parts[0],'& '+parts[1]]
        else:lines=[text]
        font='StationerySerif';margin=self.w*(.105 if style=='editorial' else .12);width=self.w-2*margin
        target=self.w*({'editorial':.215,'colour':.185,'meadow':.17}.get(style,.13))
        height=self.area*high
        size=min(target,height/(len(lines)*1.03))
        minimum=self.w*.065
        while size>=minimum:
            if all(pdfmetrics.stringWidth(line,font,size)<=width for line in lines):break
            size-=.5
        else:self.issues.append('Your names need more room. Use first names or shorten the wording.');return
        face=pdfmetrics.getFont(font).face
        if any(ord(ch) not in face.charToGlyph for ch in text if not ch.isspace()):
            self.issues.append('This design cannot print one of the characters in your names. Please use a supported spelling.');return
        total=len(lines)*size*1.03;start=self.offset+self.area*top+(height-total)/2
        for i,line in enumerate(lines):
            linew=pdfmetrics.stringWidth(line,font,size);x=margin if align=='left' else (self.w-linew)/2
            self.ops.append(('richtext',line,x,start+size+i*size*1.03,size,font,self.ink,self.accent))
    def rule(self,top,align='center'):
        x=self.w*.105 if align=='left' else self.w*.45
        self.line(x,self.offset+self.area*top,x+self.w*.10,self.offset+self.area*top,self.accent,.55)
    def tracked(self,text,top,high,size,tracking=1.5,font='StationerySans',align='center'):
        """Optical letter spacing stays real text in the PDF, with the same PNG metrics."""
        if not text:return
        size=max(9,size);width=self.w*.76
        text=text.upper();face=pdfmetrics.getFont(font).face
        if any(ord(ch) not in face.charToGlyph for ch in text if not ch.isspace()):
            self.issues.append('This design cannot print one of the characters in your text. Please use a supported spelling.');return
        def measure(t):return pdfmetrics.stringWidth(t,font,size)+max(0,len(t)-1)*tracking
        lines=[];line=''
        for word in text.split():
            if measure(word)>width:self.issues.append('Some wording is too long for this layout. Shorten it or choose a larger size.');return
            proposed=(line+' '+word).strip()
            if line and measure(proposed)>width:lines.append(line);line=word
            else:line=proposed
        if line:lines.append(line)
        if len(lines)*size*1.35>self.area*high:
            # Custom paragraphs can wrap in the same box without losing any wording.
            self.text(text,self.w*.12,self.offset+self.area*top,width,self.area*high,size,minsize=9,font=font,align=align);return
        for i,line in enumerate(lines):
            x=self.w*.105 if align=='left' else (self.w-measure(line))/2
            self.ops.append(('tracked',line,x,self.offset+self.area*top+size+i*size*1.35,size,font,self.ink,tracking))
    def decoration(self):
        c=self.config['collection'];w=self.w;h=self.area;y=self.offset
        if c=='classic':
            for inset in (w*.035,w*.047):self.rect(inset,y+inset,w-2*inset,h-2*inset,None,self.ink,.45)
        if c=='editorial':
            self.line(w*.90,y+h*.025,w*.90,y+h*.23,self.accent,.65)
            initials=''.join(part.strip()[0].upper() for part in re.split(r'\s*(?:&| and )\s*',self.config['names']) if part.strip())[:2]
            self.text(initials,w*.78,y+h*.07,w*.10,h*.10,w*.045,minsize=w*.035,colour=self.accent)
        if c=='colour':
            # Printed wavy borders: ordinary rectangular paper, no die cutting required.
            for inset,col in [(w*.044,self.ink),(w*.067,self.accent)]:
                n=150;pts=[]
                for i in range(n+1):
                    t=i/n;pts.append((inset+t*(w-2*inset),y+inset+math.sin(t*math.pi*12)*w*.008))
                for i in range(n+1):
                    t=i/n;pts.append((w-inset+math.sin(t*math.pi*12)*w*.008,y+inset+t*(h-2*inset)))
                for i in range(n+1):
                    t=i/n;pts.append((w-inset-t*(w-2*inset),y+h-inset+math.sin(t*math.pi*12)*w*.008))
                for i in range(n+1):
                    t=i/n;pts.append((inset+math.sin(t*math.pi*12)*w*.008,y+h-inset-t*(h-2*inset)))
                self.ops.append(('path',pts,col,w*.026))
        if c=='botanical':
            ratio=.18 if self.kind=='seating' else .52
            depth=.12 if self.kind=='seating' else .20 if self.kind=='menu' else .32
            self.image(artwork('botanical','top'),0,y,w*ratio,h*depth)
            bottom_ratio=.18 if self.kind=='seating' else .48
            bottom_depth=.12 if self.kind=='seating' else .20 if self.kind=='menu' else .25
            self.image(artwork('botanical','flip'),w*(1-bottom_ratio),y+h*(1-bottom_depth),w*bottom_ratio,h*bottom_depth)
        if c=='meadow':
            if self.kind=='seating':self.image(artwork('meadow'),0,y+h*.84,w,h*.16)
            elif self.kind in ('place','table'):
                sprig=artwork('meadow-sprig');aw=w*.28;ah=min(h*.33,aw*sprig.height/sprig.width)
                self.image(sprig,w-aw,y+h-ah,aw,ah)
            else:self.image(artwork('meadow-frame'),0,y+h*.20,w,h*.80)
        if self.offset:self.line(0,self.offset,w,self.offset,'#d6d2ca',.25)


def build_layout(config,kind,state,photo=None,guest=None,table=None):
    width,height=(v*MM for v in SIZES[config['size']]);p=Layout(width,height,config,kind);p.decoration();w=width;h=p.area;y=p.offset
    margin=w*.12;cw=w-2*margin;c=config['collection'];small=w*.033
    def txt(t,top,high,size=1,font='StationerySerif',colour=None,align='center'):
        p.text(t,margin,y+h*top,cw,h*high,max(9,small*size),minsize=max(9,small*size*.72),font=font,colour=colour,align=align)
    initials=' & '.join(word[0].upper() for word in re.split(r'\s*(?:&| and )\s*',config['names']) if word)[:12]
    def title(text,top=.12,size=.18):
        p.text(text,margin,y+h*top,cw,h*.17,w*size,minsize=w*.09)
    def monogram(top=.10):
        p.text(initials,margin,y+h*top,cw,h*.10,w*.065,minsize=w*.04,font='StationeryItalic',colour=p.accent)
    if c=='classic' and kind not in ('place','seating'):monogram()
    # Photo templates require a real uploaded photograph only where one is used.
    has_photo=c=='photo' and kind in ('day','evening','save_date','welcome','thanks')
    if has_photo and photo is not None:
        art=photo
        if config['photo_mode']=='mono':art=ImageOps.grayscale(photo).convert('RGB')
        ph=h*(.58 if kind=='welcome' else .47);target=(max(1,int(w*4)),max(1,int(ph*4)));art=crop_photo(art,target,config)
        p.image(art,0,h*.42 if kind=='welcome' else 0,w,ph)
    if has_photo and photo is None:
        photo_y=h*.42 if kind=='welcome' else 0;photo_h=h*.58 if kind=='welcome' else h*.47
        p.rect(0,photo_y,w,photo_h,'#e8e4dd');p.text('Your photograph',w*.1,photo_y+photo_h*.42,w*.8,h*.1,w*.055,font='StationerySans',colour='#655e55');p.issues.append('Choose your photograph for Photo Story.')
    if kind in ('day','evening','save_date'):
        if not config['names']:p.issues.append('Add your names.')
        if not config['date']:p.issues.append('Add your wedding date before downloading.')
        if kind in ('day','evening') and not config['venue']:p.issues.append('Add the venue for this invitation.')
        if kind in ('day','evening') and not config['arrival']:p.issues.append('Add the arrival time for this invitation.')
        if has_photo:
            p.tracked(config['intro'] if kind!='save_date' else 'Save the date',.50,.045,w*.024,.9)
            p.names(config['names'],.55,.12)
            p.tracked(config['message'],.69,.065,w*.025,.9,font='StationerySerif')
            p.rule(.77);p.tracked(readable_date(config['date']),.79,.045,w*.030,1.2,font='StationerySerif')
            p.tracked(config['venue'],.845,.045,w*.027,1.2,font='StationerySerif')
            txt(config['arrival'],.89,.045,.84);txt(config['closing'],.95,.035,.78,'StationeryItalic')
        elif c=='editorial':
            p.tracked(config['intro'] if kind!='save_date' else 'Save the date',.17,.06,w*.026,1.6,align='left')
            p.names(config['names'],.25,.31,'editorial','left')
            p.tracked(config['message'],.60,.08,w*.025,1.2,align='left')
            p.rule(.70,'left');p.tracked(readable_date(config['date']),.735,.06,w*.032,1.5,font='StationerySerif',align='left')
            p.tracked(config['venue'],.805,.05,w*.028,1.8,font='StationerySerif',align='left')
            txt(config['arrival'],.86,.05,.94,align='left');p.tracked(config['closing'],.93,.045,w*.024,1.1,align='left')
        elif c=='meadow':
            txt(config['intro'] if kind!='save_date' else 'Save the date',.095,.06,1.1,'StationeryItalic')
            p.names(config['names'],.155,.31,'meadow')
            txt(config['message'],.495,.065,1.08,'StationeryItalic')
            p.tracked(readable_date(config['date']),.565,.06,w*.032,1.35,font='StationerySerif')
            p.tracked(config['venue'],.63,.055,w*.029,1.6,font='StationerySerif')
            txt(config['arrival'],.695,.055,.97);txt(config['closing'],.755,.055,.94,'StationeryItalic')
        elif c=='colour':
            txt(config['intro'] if kind!='save_date' else 'Save the date',.16,.06,1.05)
            p.names(config['names'],.255,.29,'colour')
            txt(config['message'],.59,.07,1.08);p.rule(.69)
            p.tracked(readable_date(config['date']),.73,.055,w*.031,1.2,font='StationerySerif')
            p.tracked(config['venue'],.795,.05,w*.028,1.3,font='StationerySerif')
            txt(config['arrival'],.85,.05,.95);txt(config['closing'],.91,.045,.93,'StationeryItalic')
        else:
            p.tracked(config['intro'] if kind!='save_date' else 'Save the date',.28,.07,w*.026,1.4,font='StationerySerif' if c=='classic' else 'StationerySans')
            p.names(config['names'],.365,.13)
            p.tracked(config['message'],.525,.095,w*.027,1.2,font='StationerySerif' if c=='classic' else 'StationerySans')
            p.rule(.635);p.tracked(readable_date(config['date']),.675,.06,w*.035,1.4,font='StationerySerif')
            p.tracked(config['venue'],.75,.05,w*.029,1.5,font='StationerySerif' if c=='classic' else 'StationerySans')
            txt(config['arrival'],.815,.055,1.0,'StationeryItalic' if c=='classic' else 'StationerySerif')
            txt(config['closing'],.885,.045,.94,'StationeryItalic')
        if config['recipient']:txt(config['recipient'],.055 if c!='classic' else .20,.04,.8,'StationerySans')
    elif kind=='welcome':
        top=.08 if has_photo else .24 if c in ('classic','botanical') else .12
        p.tracked('Welcome to the wedding of',top,.09,w*.026, w*.005)
        ntop=.17 if has_photo else .35 if c in ('classic','botanical') else .26
        style=c if c in ('editorial','meadow','colour') else 'inline'
        p.names(config['names'],ntop,.15 if has_photo or style=='inline' else .34,style,'left' if c=='editorial' else 'center')
        dt=.35 if has_photo else .70 if style=='inline' else .72
        p.rule(dt-.04);p.tracked(date.fromisoformat(config['date']).strftime('%d %B %Y').lstrip('0') if config['date'] else 'Wedding date to confirm',dt,.08,w*.037,w*.006,font='StationerySerif')
        if not config['names']:p.issues.append('Add your names.')
        if not config['date']:p.issues.append('Add your wedding date before downloading.')
    elif kind=='menu':
        title('Menu',.23 if c=='classic' else .13,.20);p.rule(.34)
        courses=[block.strip().splitlines() for block in re.split(r'\n\s*\n',config['menu']) if block.strip()]
        if 1<=len(courses)<=4:
            top=.36 if c=='meadow' else .41;cell=(.39 if c=='meadow' else .43)/len(courses)
            for i,lines in enumerate(courses):
                pos=top+i*cell
                p.tracked(lines[0],pos,cell*.30,w*.030,w*.006,font='StationerySerif' if c in ('classic','colour','photo') else 'StationerySans')
                p.text('\n'.join(lines[1:]),margin,y+h*(pos+cell*.32),cw,h*cell*.55,w*.047,minsize=9)
                if i<len(courses)-1:p.rule(pos+cell*.94)
        else:txt(config['menu'],.41,.43,1.35)
        if not config['menu']:p.issues.append('Add your menu.')
    elif kind=='place':
        name=guest['name'] if guest else config['recipient']
        if c in ('classic','photo'):monogram(.09)
        p.text(name or 'Guest name',margin,y+h*.40,cw,h*.31,w*.108,minsize=10,font='StationeryItalic' if c=='editorial' else 'StationerySerif')
        if not name:p.issues.append('Choose a guest or enter a name.')
    elif kind=='table':
        p.tracked('Table',.26,.09,w*.034,w*.006)
        title(table or config['table_name'] or 'Table name',.43,.22);p.rule(.70)
        if not (table or config['table_name']):p.issues.append('Choose or enter a table name.')
    elif kind=='thanks':
        title('Thank you',.51 if has_photo else .25,.17);txt(config['message'],.68 if has_photo else .46,.15,1.12,'StationeryItalic')
        p.names(config['names'],.86 if has_photo else .61 if c=='meadow' else .65,.10)
    elif kind=='seating':
        txt('Find your table',.09,.09,2.9);txt(config['names'],.20,.06,1.1)
        guests=selected_guests(state,config);groups={}
        for g in guests:
            if not g.get('table'):p.issues.append('Seat every selected guest before downloading the seating chart.');continue
            groups.setdefault(g['table'],[]).append(g['name'])
        if not guests:p.issues.append('There are no guests in this selection.')
        count=len(groups);cols=2 if count<=8 else 3;rows=math.ceil(max(1,count)/cols);top=h*.31;bottom=h*.79;gap=w*.05;colw=(cw-gap*(cols-1))/cols;cell=(bottom-top)/rows
        for i,(name,members) in enumerate(sorted(groups.items(),key=lambda v:v[0].casefold())):
            x=margin+(i%cols)*(colw+gap);yy=top+(i//cols)*cell
            p.text(name,x,yy,colw,cell*.25,w*.047,minsize=w*.035,colour=p.accent)
            minimum=18 if config['size']=='A1' else 14 if config['size']=='A2' else 11
            p.text('\n'.join(sorted(members,key=str.casefold)),x,yy+cell*.26,colw,cell*.68,max(minimum,min(w*.028,cell*.6/max(1,len(members))/1.2)),minsize=minimum)
        if count>18:p.issues.append('This chart supports up to 18 tables. Use separate charts for larger rooms.')
    return p


def placecard_sheets(cards):
    """A4 cutting sheets retain each card's actual dimensions and an optional fold."""
    w,h=210*MM,297*MM;cw,ch=cards[0].w,cards[0].h;gap=6*MM
    cols=2;rows=max(1,int((h-20*MM+gap)//(ch+gap)));per=cols*rows;pages=[]
    for start in range(0,len(cards),per):
        sheet=Layout(w,h,cards[0].config,'sheet');sheet.ops=[('rect',0,0,w,h,'#ffffff',None,.5)]
        x0=(w-cols*cw-gap*(cols-1))/2;y0=(h-rows*ch-gap*(rows-1))/2
        for i,card in enumerate(cards[start:start+per]):
            dx=x0+(i%cols)*(cw+gap);dy=y0+(i//cols)*(ch+gap)
            for op in card.ops:
                if op[0]=='rect':_,x,y,ww,hh,fill,stroke,lw=op;sheet.ops.append(('rect',x+dx,y+dy,ww,hh,fill,stroke,lw))
                elif op[0]=='line':_,x,y,xx,yy,col,lw=op;sheet.ops.append(('line',x+dx,y+dy,xx+dx,yy+dy,col,lw))
                elif op[0]=='text':_,text,x,y,size,font,col=op;sheet.ops.append(('text',text,x+dx,y+dy,size,font,col))
                elif op[0] in ('richtext','tracked'):
                    tag,text,x,y,size,font,col,extra=op;sheet.ops.append((tag,text,x+dx,y+dy,size,font,col,extra))
                elif op[0]=='image':_,pic,x,y,ww,hh=op;sheet.ops.append(('image',pic,x+dx,y+dy,ww,hh))
                elif op[0]=='path':_,pts,col,lw=op;sheet.ops.append(('path',[(x+dx,y+dy) for x,y in pts],col,lw))
            for x,y,sx,sy in [(dx,dy,-1,-1),(dx+cw,dy,1,-1),(dx,dy+ch,-1,1),(dx+cw,dy+ch,1,1)]:
                sheet.line(x+sx*MM,y,x+sx*2.5*MM,y,'#777777',.25);sheet.line(x,y+sy*MM,x,y+sy*2.5*MM,'#777777',.25)
        pages.append(sheet)
    return pages


def draw_pdf(layouts,bleed=0):
    out=io.BytesIO();b=bleed*MM;readers={};c=canvas.Canvas(out,pagesize=(layouts[0].w+2*b,layouts[0].h+2*b),pageCompression=1,initialFontName='StationerySerif')
    c.setTitle('Wedding stationery');c.setAuthor('Ivory Digital · Weddings By Mark')
    for p in layouts:
        c.setPageSize((p.w+2*b,p.h+2*b));c.setCropBox((b,b,p.w+b,p.h+b),name='trim');c.setFillColor(HexColor(p.bg));c.rect(0,0,p.w+2*b,p.h+2*b,fill=1,stroke=0);c.saveState();c.translate(b,b)
        for op in p.ops:
            if op[0]=='rect':
                _,x,y,w,h,fill,stroke,lw=op;c.setLineWidth(lw)
                if fill:c.setFillColor(HexColor(fill))
                if stroke:c.setStrokeColor(HexColor(stroke))
                c.rect(x,p.h-y-h,w,h,fill=int(bool(fill)),stroke=int(bool(stroke)))
            elif op[0]=='line':
                _,x,y,xx,yy,col,lw=op;c.setStrokeColor(HexColor(col));c.setLineWidth(lw);c.line(x,p.h-y,xx,p.h-yy)
            elif op[0]=='path':
                _,pts,col,lw=op;path=c.beginPath();path.moveTo(pts[0][0],p.h-pts[0][1])
                for x,y in pts[1:]:path.lineTo(x,p.h-y)
                path.close();c.setStrokeColor(HexColor(col));c.setLineWidth(lw);c.setLineJoin(1);c.drawPath(path)
            elif op[0]=='text':
                _,text,x,y,size,font,col=op;c.setFont(font,size);c.setFillColor(HexColor(col));c.drawString(x,p.h-y,text)
            elif op[0] in ('richtext','tracked'):
                tag,text,x,y,size,font,col,extra=op;run=c.beginText(x,p.h-y);run.setFont(font,size);run.setFillColor(HexColor(col))
                if tag=='tracked':run.setCharSpace(extra);run.textOut(text)
                else:
                    for chunk in re.split('(&)',text):
                        run.setFillColor(HexColor(extra if chunk=='&' else col));run.textOut(chunk)
                c.drawText(run)
            elif op[0]=='image':
                _,img,x,y,w,h=op
                if id(img) not in readers:readers[id(img)]=ImageReader(img)
                c.drawImage(readers[id(img)],x,p.h-y-h,w,h,mask='auto')
        c.restoreState();c.showPage()
    c.save();return out.getvalue()


def draw_png(p,long_edge=1600):
    scale=long_edge/max(p.w,p.h);img=Image.new('RGB',(round(p.w*scale),round(p.h*scale)),p.bg);d=ImageDraw.Draw(img)
    for op in p.ops:
        if op[0]=='rect':
            _,x,y,w,h,fill,stroke,lw=op;d.rectangle((x*scale,y*scale,(x+w)*scale,(y+h)*scale),fill=fill,outline=stroke,width=max(1,round(lw*scale)))
        elif op[0]=='line':
            _,x,y,xx,yy,col,lw=op;d.line((x*scale,y*scale,xx*scale,yy*scale),fill=col,width=max(1,round(lw*scale)))
        elif op[0]=='path':
            _,pts,col,lw=op;points=[(x*scale,y*scale) for x,y in pts];stroke=max(1,round(lw*scale));d.line(points+[points[0]],fill=col,width=stroke)
            # Explicit round joins avoid Pillow's short-segment gaps in thick scalloped borders.
            radius=stroke/2
            for x,y in points:d.ellipse((x-radius,y-radius,x+radius,y+radius),fill=col)
        elif op[0] in ('text','richtext','tracked'):
            _,text,x,y,size,font,col,*extra=op
            file={'StationerySerif':'CormorantGaramond-Regular.ttf','StationeryItalic':'CormorantGaramond-Italic.ttf','StationerySans':'Outfit-Regular.ttf'}[font]
            f=ImageFont.truetype(str(ASSETS/'fonts'/file),max(1,round(size*scale)))
            if op[0]=='text':d.text((x*scale,y*scale),text,font=f,fill=col,anchor='ls')
            elif op[0]=='tracked':
                for char in text:
                    d.text((x*scale,y*scale),char,font=f,fill=col,anchor='ls');x+=pdfmetrics.stringWidth(char,font,size)+extra[0]
            else:
                for chunk in re.split('(&)',text):
                    d.text((x*scale,y*scale),chunk,font=f,fill=extra[0] if chunk=='&' else col,anchor='ls');x+=pdfmetrics.stringWidth(chunk,font,size)
        elif op[0]=='image':
            _,pic,x,y,w,h=op;pic=pic.resize((max(1,round(w*scale)),max(1,round(h*scale))),Image.Resampling.LANCZOS);img.paste(pic,(round(x*scale),round(y*scale)),pic if pic.mode=='RGBA' else None)
    out=io.BytesIO();img.save(out,'PNG',optimize=True);return out.getvalue()


def register_stationery(app,db,auth,wedding,json_body,audit,rate):
    def kind_of(kind):
        if kind not in KINDS:abort(404)
        return kind
    def existing(wid,kind):return db().execute('SELECT * FROM stationery_drafts WHERE wedding_id=? AND kind=?',(wid,kind)).fetchone()
    def photo_for(w,config):
        if not config['photo']:return None
        f=db().execute('SELECT * FROM uploads WHERE id=? AND wedding_id=? AND kind="cover"',(config['photo'],w['id'])).fetchone()
        if not f:raise ValueError('Choose a photograph from your own documents & cover photos.')
        path=Path(app.config['DATA_DIR'])/'files'/w['id']/Path(f['path']).name
        try:
            image=Image.open(path);image.load();return image.convert('RGB')
        except (OSError,ValueError):raise ValueError('That photograph is unavailable. Choose another.')
    def layouts_for(w,kind,config,batch=False):
        state=json.loads(w['state']);photo=photo_for(w,config);guests=selected_guests(state,config)
        if kind=='place' and batch:
            if not guests:raise ValueError('There are no guests in this selection.')
            if len(guests)>250:raise ValueError('Download place cards in smaller selections (up to 250 guests).')
            return [build_layout(config,kind,state,photo,guest=g) for g in guests]
        if kind=='table' and batch:
            tables=sorted({g.get('table','') for g in guests if g.get('table')},key=str.casefold)
            if not tables:raise ValueError('Add table assignments first, or download one table card.')
            return [build_layout(config,kind,state,photo,table=t) for t in tables]
        guest=next((g for g in guests if g['id']==config['guest_id']),None) if config['guest_id'] else None
        if config['guest_id'] and guest is None:raise ValueError('That guest is no longer in this selection. Choose another.')
        return [build_layout(config,kind,state,photo,guest=guest)]
    @app.get('/stationery')
    @auth()
    def stationery_page():wedding();return render_template('stationery.html')
    @app.get('/api/stationery')
    @auth()
    def stationery_get():
        w=wedding();state=json.loads(w['state']);drafts={}
        for kind in KINDS:
            row=existing(w['id'],kind);current=source(state,kind)
            drafts[kind]={'data':validate(json.loads(row['data']),kind) if row else defaults(state,kind),'revision':row['revision'] if row else 0,'source':current,'review_needed':bool(row and row['source_hash']!=current),'download_outdated':bool(row and row['exported_at'] and (row['exported_source']!=current or row['exported_revision']!=row['revision'])),'exported_at':row['exported_at'] if row else None}
        return jsonify(collections=COLLECTIONS,kinds=KINDS,sizes={k:{'name':LABELS.get(k,k),'mm':v} for k,v in SIZES.items()},drafts=drafts,defaults={k:defaults(state,k) for k in KINDS},guests=[{k:g[k] for k in ('id','name','table','rsvp')} for g in state['guests']],photos=[dict(r) for r in db().execute('SELECT id,name FROM uploads WHERE wedding_id=? AND kind="cover"',(w['id'],))],readonly=w['access_until']<date.today().isoformat())
    @app.get('/api/stationery/collections/<collection>.png')
    @auth()
    def stationery_collection(collection):
        if collection not in COLLECTIONS:abort(404)
        w=wedding();rate('stationery-thumbnails-'+w['id'],300,900,per_ip=False);state=json.loads(w['state']);data=defaults(state,'day')
        data.update(collection=collection,palette=next(iter(COLLECTIONS[collection]['palettes'])),names=data['names'] or 'Your names',venue=data['venue'] or 'Your venue',arrival='Your arrival details')
        photo=None
        if collection=='photo':
            row=db().execute('SELECT id FROM uploads WHERE wedding_id=? AND kind="cover" ORDER BY created DESC LIMIT 1',(w['id'],)).fetchone()
            if row:
                data['photo']=row['id'];photo=photo_for(w,data)
        if not RENDER_LOCK.acquire(timeout=3):abort(429,description='Your collection preview is busy. Please try again.')
        try:raw=draw_png(build_layout(data,'day',state,photo),500)
        finally:RENDER_LOCK.release()
        return send_file(io.BytesIO(raw),mimetype='image/png')
    @app.put('/api/stationery/<kind>')
    @auth()
    def stationery_save(kind):
        kind_of(kind);body=json_body();config=validate(body.get('data'),kind);db().execute('BEGIN IMMEDIATE');w=wedding(True);current=source(json.loads(w['state']),kind);row=existing(w['id'],kind)
        if type(body.get('revision')) is not int or body['revision']!=(row['revision'] if row else 0):abort(409,description='Your partner changed this design. Keep your wording and reload before saving.')
        if body.get('source')!=current:abort(409,description='Your wedding details or guests changed. Keep your wording and reload to review them.')
        photo_for(w,config);revision=(row['revision'] if row else 0)+1
        db().execute('INSERT INTO stationery_drafts(wedding_id,kind,revision,data,source_hash,updated) VALUES(?,?,?,?,?,?) ON CONFLICT(wedding_id,kind) DO UPDATE SET revision=excluded.revision,data=excluded.data,source_hash=excluded.source_hash,updated=excluded.updated',(w['id'],kind,revision,json.dumps(config),current,time.time()))
        audit('Stationery draft saved: '+kind,w['id']);return jsonify(revision=revision,source=current)
    @app.post('/api/stationery/<kind>/preview')
    @auth()
    def stationery_preview(kind):
        kind_of(kind);w=wedding();rate('stationery-preview-'+w['id'],300,900,per_ip=False);config=validate(json_body().get('data'),kind)
        if not RENDER_LOCK.acquire(blocking=False):abort(429,description='Another preview is being prepared. Please try again in a moment.')
        try:
            p=layouts_for(w,kind,config)[0];result=draw_png(p,900)
            return jsonify(image='data:image/png;base64,'+__import__('base64').b64encode(result).decode(),issues=list(dict.fromkeys(p.issues)))
        finally:RENDER_LOCK.release()
    @app.post('/api/stationery/<kind>/download')
    @auth()
    def stationery_download(kind):
        kind_of(kind);body=json_body();w=wedding();rate('stationery-export-'+w['id'],60,900,per_ip=False);row=existing(w['id'],kind)
        if not row:raise ValueError('Save and preview this design before downloading.')
        current=source(json.loads(w['state']),kind)
        if type(body.get('revision')) is not int or body.get('revision')!=row['revision'] or body.get('source')!=current or row['source_hash']!=current:abort(409,description='The design or your wedding details changed. Review, save and preview the latest version.')
        fmt=body.get('format');bleed=body.get('bleed',0);batch=body.get('batch',False)
        if fmt not in ('pdf','png') or type(bleed) is not int or bleed not in (0,3) or type(batch) is not bool or batch and (kind not in ('place','table') or fmt!='pdf'):raise ValueError('Choose PDF or a single sharing image.')
        if not RENDER_LOCK.acquire(blocking=False):abort(429,description='Another download is being prepared. Please try again shortly.')
        try:
            layouts=layouts_for(w,kind,json.loads(row['data']),batch);issues=[i for p in layouts for i in p.issues]
            if issues:raise ValueError(' '.join(dict.fromkeys(issues)))
            if batch and kind=='place':layouts=placecard_sheets(layouts);bleed=0
            result=draw_pdf(layouts,bleed) if fmt=='pdf' else draw_png(layouts[0],1800)
        finally:RENDER_LOCK.release()
        # Do not label an older snapshot current if a partner edited during rendering.
        db().execute('UPDATE stationery_drafts SET exported_source=?,exported_revision=?,exported_at=? WHERE wedding_id=? AND kind=? AND revision=?',(current,row['revision'],time.time(),w['id'],kind,row['revision']))
        return send_file(io.BytesIO(result),mimetype='application/pdf' if fmt=='pdf' else 'image/png',as_attachment=True,download_name=f'our-{kind}-r{row["revision"]}.{fmt}')
