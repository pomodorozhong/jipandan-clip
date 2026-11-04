# ARCHIVED PROVENANCE. Copied from clip-ranking-experiment-2026-10-11/scripts/wfeat.py, with only the hard-coded private paths replaced
# by environment variables. These scripts produced the frozen legacy inputs that the tracked
# ranking pipeline starts from, and were NOT rerun for the 2026-11-01 report (librosa,
# mlx-whisper and sentence-transformers are not locked here, so a rerun would not be pinned). The outputs they made are verified by SHA-256 in input-hashes.json instead.
#   JIPANDAN_LEGACY_RAW: folder holding <rec>.mp3, <rec>.srt and the reviewed session JSON files
import os,json,subprocess,sys,time,math,numpy as np,mlx.core as mx
from mlx_whisper.load_models import load_model
from mlx_whisper.audio import log_mel_spectrogram,pad_or_trim,N_SAMPLES
from mlx_whisper.decoding import DecodingOptions,decode
R=os.environ['JIPANDAN_LEGACY_RAW'].rstrip('/')+'/'
recs={'0511':(R+'0511.mp3',R+'0511.jipandan.json'),'0526':(R+'0526.mp3',R+'0526.jipandan.json'),'0602':(R+'0602.mp3',R+'0602.jipandan_.json'),'0614':(R+'0614.mp3',R+'0614.jipandan.json')}
def t(s):h,m,r=s.replace(',','.').split(':');return int(h)*3600+int(m)*60+float(r)
model=load_model('mlx-community/whisper-large-v3-mlx',dtype=mx.float16)
opt=DecodingOptions(language='zh',without_timestamps=True,fp16=True,temperature=0.0)
meta=[];embs=[];B=16
for k,(a,j) in recs.items():
    t0=time.time()
    x=np.frombuffer(subprocess.run(['ffmpeg','-v','quiet','-i',a,'-ac','1','-ar','16000','-f','f32le','-'],capture_output=True).stdout,np.float32)
    C=[c for c in json.load(open(j))['candidates'] if not c.get('suffix') and c['status']!='pending']
    for b in range(0,len(C),B):
        cs=C[b:b+B];mels=[];durs=[]
        for c in cs:
            s,e=t(c['original_start']),t(c['original_end']);e=min(e,s+30);durs.append(e-s)
            seg=x[int(s*16000):int(e*16000)]
            if len(seg)<1600:seg=np.pad(seg,(0,1600-len(seg)))
            mels.append(pad_or_trim(log_mel_spectrogram(seg,n_mels=128),3000,axis=-2))
        enc=model.encoder(mx.stack(mels).astype(mx.float16))
        res=decode(model,enc,opt)
        e32=np.array(enc.astype(mx.float32))
        for i,(c,r,d) in enumerate(zip(cs,res,durs)):
            n=min(1500,math.ceil(d*50)+1);v=e32[i,:n]
            embs.append(np.r_[v.mean(0),v.std(0)].astype(np.float16))
            meta.append(dict(rec=k,idx=c['index'],avg_logprob=r.avg_logprob,no_speech_prob=r.no_speech_prob,compression_ratio=r.compression_ratio,wtext=r.text))
        if b%320==0:print(k,b,'/',len(C),round(time.time()-t0),'s',flush=True)
    print(k,'done',len(C),round(time.time()-t0),'s',flush=True);del x
    json.dump(meta,open(sys.argv[1]+'.json','w'),ensure_ascii=False,default=float);np.save(sys.argv[1]+'.npy',np.stack(embs))
json.dump(meta,open(sys.argv[1]+'.json','w'),ensure_ascii=False,default=float);np.save(sys.argv[1]+'.npy',np.stack(embs))
