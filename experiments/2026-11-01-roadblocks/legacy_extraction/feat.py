# ARCHIVED PROVENANCE. Copied from clip-ranking-experiment-2026-10-11/scripts/feat.py, with only the hard-coded private paths replaced
# by environment variables. These scripts produced the frozen legacy inputs that the tracked
# ranking pipeline starts from, and were NOT rerun for the 2026-11-01 report (librosa,
# mlx-whisper and sentence-transformers are not locked here, so a rerun would not be pinned). The outputs they made are verified by SHA-256 in input-hashes.json instead.
#   JIPANDAN_LEGACY_RAW: folder holding <rec>.mp3, <rec>.srt and the reviewed session JSON files
import os,json,subprocess,numpy as np,librosa,sys,time
R=os.environ['JIPANDAN_LEGACY_RAW'].rstrip('/')+'/'
recs={'0511':(R+'0511.mp3',R+'0511.jipandan.json'),'0526':(R+'0526.mp3',R+'0526.jipandan.json'),
 '0602':(R+'0602.mp3',R+'0602.jipandan_.json'),'0614':(R+'0614.mp3',R+'0614.jipandan.json'),
 '0903':(R+'0903.mp3',R+'0903.jipandan.json')}
def t(s):h,m,r=s.replace(',','.').split(':');return int(h)*3600+int(m)*60+float(r)
sr=16000;hop=160
out=[]
for k,(a,j) in recs.items():
    t0=time.time()
    x=np.frombuffer(subprocess.run(['ffmpeg','-v','quiet','-i',a,'-ac','1','-ar',str(sr),'-f','f32le','-'],capture_output=True).stdout,np.float32)
    n=len(x)//hop;db=20*np.log10(np.maximum(np.sqrt((x[:n*hop].reshape(n,hop)**2).mean(1)),1e-6))
    gfloor=np.percentile(db,20)
    C=[c for c in json.load(open(j))['candidates'] if not c.get('suffix')]
    for c in C:
        s,e=t(c['original_start']),t(c['original_end']);fs,fe=int(s*100),max(int(e*100),int(s*100)+5)
        w=db[fs:fe];ctx=db[max(0,fs-3000):fe+3000]
        pre=db[max(0,fs-50):fs];post=db[fe:fe+50]
        y=x[int(s*sr):int(e*sr)]
        f={'rec':k,'idx':c['index'],'status':c['status'],'txt':c.get('source_text') or c['title'],'dur':e-s,
           'db_mean':w.mean(),'db_max':w.max(),'db_std':w.std(),'db_p90':np.percentile(w,90),
           'rel_ctx':np.percentile(w,90)-np.percentile(ctx,50),'rel_floor':np.percentile(w,90)-gfloor,
           'active_frac':(w>np.percentile(ctx,30)+10).mean(),
           'pre_db':(pre.mean() if len(pre) else -60)-np.percentile(ctx,30),'post_db':(post.mean() if len(post) else -60)-np.percentile(ctx,30),
           'gap_prev':s-prev_e if (prev_e:=out[-1]['_e'] if out and out[-1]['rec']==k else None) is not None else 5,'_e':e}
        if len(y)>=2048:
            f0,vf,vp=librosa.pyin(y[:sr*6],fmin=70,fmax=700,sr=sr,frame_length=1024,hop_length=320)
            v=f0[~np.isnan(f0)]
            st=12*np.log2(v/100) if len(v) else np.array([0.])
            f.update(voiced=vf.mean(),f0_med=np.median(st),f0_std=st.std(),f0_range=np.ptp(st),f0_slope=(st[-1]-st[0]) if len(st)>1 else 0)
            S_=np.abs(librosa.stft(y[:sr*6],n_fft=512,hop_length=160))
            f.update(centroid=librosa.feature.spectral_centroid(S=S_,sr=sr).mean(),flat=librosa.feature.spectral_flatness(S=S_).mean(),
                     zcr=librosa.feature.zero_crossing_rate(y[:sr*6]).mean(),onsets=len(librosa.onset.onset_detect(y=y[:sr*6],sr=sr))/max(e-s,.1))
        out.append(f)
    print(k,len(C),round(time.time()-t0),'s',flush=True);del x
for f in out:f.pop('_e')
json.dump(out,open(sys.argv[1],'w'),ensure_ascii=False,default=float)
