# ARCHIVED PROVENANCE. Copied from clip-ranking-experiment-2026-10-12-embeddinggemma2/scripts/embed.py, with only the hard-coded private paths replaced
# by environment variables. These scripts produced the frozen legacy inputs that the tracked
# ranking pipeline starts from, and were NOT rerun for the 2026-11-01 report (librosa,
# mlx-whisper and sentence-transformers are not locked here, so a rerun would not be pinned). The outputs they made are verified by SHA-256 in input-hashes.json instead.
#   JIPANDAN_LEGACY_RAW: folder holding <rec>.mp3, <rec>.srt and the reviewed session JSON files
#   JIPANDAN_LEGACY_SESSIONS: folder holding the reviewed session JSON files (inputs/sessions)
# EmbeddingGemma 2 embeddings for every reviewed candidate.
#   srt version:      audio cut at SRT bounds, SRT text            (all reviewed rows; known before review)
#   exported version: audio cut at user-trimmed bounds, edited title (kept rows only; known after review)
import os,json,subprocess,sys,time,numpy as np,torch
from sentence_transformers import SentenceTransformer
OUT=sys.argv[1]
SES=os.environ['JIPANDAN_LEGACY_SESSIONS'].rstrip('/')+'/'
RAW=os.environ['JIPANDAN_LEGACY_RAW'].rstrip('/')+'/'
S={'0511':'0511.jipandan.json','0526':'0526.jipandan.json','0602':'0602.jipandan_.json','0614':'0614.jipandan.json'}
SR=16000;MAXS=30.0
def ts(x):h,m,s=x.split(':');return int(h)*3600+int(m)*60+float(s)
def srt(p):
    o={}
    for b in open(p,encoding='utf-8-sig').read().strip().split('\n\n'):
        L=b.strip().split('\n');o[int(L[0])]=' '.join(L[2:]).strip()
    return o
def load(p):
    raw=subprocess.run(['ffmpeg','-v','error','-i',p,'-ac','1','-ar',str(SR),'-f','s16le','-'],capture_output=True,check=True).stdout
    return np.frombuffer(raw,np.int16)
m=SentenceTransformer("google/embeddinggemma-2",device="mps",model_kwargs={"torch_dtype":torch.bfloat16},config_kwargs={"vision_config":None})
meta=[];AS=[];AE=[];TS=[];TE=[]
for r,f in S.items():
    C=[c for c in json.load(open(SES+f))['candidates'] if c['status']!='pending'];T=srt(RAW+r+'.srt');pcm=load(RAW+r+'.mp3');t0=time.time()
    def cut(s,d):a=pcm[int(s*SR):int((s+min(max(d,.2),MAXS))*SR)].astype(np.float32)/32768;return {"audio":{"array":a,"sampling_rate":SR}}
    for c in C:
        kept=c['status']!='skipped';os_=ts(c['original_start']);od=ts(c['original_end'])-os_
        meta.append({'rec':r,'idx':c['index'],'status':c['status'],'srt_text':T[c['index']],'title':c['title'],
                     'orig':[os_,od],'trim':[ts(c['start']),float(c['duration'])]})
    rows=meta[-len(C):]
    AS.append(m.encode([cut(*d['orig']) for d in rows],batch_size=16,normalize_embeddings=True))
    K=[d for d in rows if d['status']!='skipped']
    AE.append(m.encode([cut(*d['trim']) for d in K],batch_size=16,normalize_embeddings=True))
    print(r,len(rows),'rows',len(K),'kept',f'{time.time()-t0:.0f}s',flush=True)
TS=m.encode([d['srt_text'] for d in meta],prompt_name='Classification',batch_size=64,normalize_embeddings=True)
TE=m.encode([d['title'] for d in meta if d['status']!='skipped'],prompt_name='Classification',batch_size=64,normalize_embeddings=True)
np.savez(OUT+'/eg2.npz',audio_srt=np.concatenate(AS),audio_exp=np.concatenate(AE),text_srt=TS,text_exp=TE)
json.dump(meta,open(OUT+'/eg2_meta.json','w'),ensure_ascii=False)
print('done')
