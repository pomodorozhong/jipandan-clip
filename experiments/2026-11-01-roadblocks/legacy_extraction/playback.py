# ARCHIVED PROVENANCE. Copied from clip-ranking-experiment-2026-10-11/scripts/playback.py, with only the hard-coded private paths replaced
# by environment variables. These scripts produced the frozen legacy inputs that the tracked
# ranking pipeline starts from, and were NOT rerun for the 2026-11-01 report (librosa,
# mlx-whisper and sentence-transformers are not locked here, so a rerun would not be pinned). The outputs they made are verified by SHA-256 in input-hashes.json instead.
#   JIPANDAN_LEGACY_RAW: folder holding <rec>.mp3, <rec>.srt and the reviewed session JSON files
import os,json,subprocess,sys,time,numpy as np
R=os.environ['JIPANDAN_LEGACY_RAW'].rstrip('/')+'/'
recs={'0511':'0511.jipandan.json','0526':'0526.jipandan.json','0602':'0602.jipandan_.json','0614':'0614.jipandan.json'}
def t(s):h,m,r=s.replace(',','.').split(':');return int(h)*3600+int(m)*60+float(r)
sr=16000;nfft=512;hop=160
fr=np.fft.rfftfreq(nfft,1/sr)
bands={'b_lo':(50,200),'b_lomid':(200,500),'b_mid':(500,2000),'b_himid':(2000,4000),'b_hi':(4000,8000)}
win=np.hanning(nfft)
out=[]
for k,j in recs.items():
    t0=time.time()
    x=np.frombuffer(subprocess.run(['ffmpeg','-v','quiet','-i',R+k+'.mp3','-ac','1','-ar',str(sr),'-f','f32le','-'],capture_output=True).stdout,np.float32)
    C=[c for c in json.load(open(R+j))['candidates'] if not c.get('suffix') and c['status']!='pending']
    for c in C:
        s,e=t(c['original_start']),t(c['original_end']);y=x[int(s*sr):int(min(e,s+8)*sr)].astype(np.float64)
        f={'rec':k,'idx':c['index']}
        if len(y)<nfft*4:out.append(f);continue
        fr_=np.lib.stride_tricks.sliding_window_view(y,nfft)[::hop]*win
        P=np.abs(np.fft.rfft(fr_,axis=1))**2+1e-12
        edb=10*np.log10(P.sum(1));loud=edb>=np.percentile(edb,60)   # loudest 40% frames = dominant source
        Pl=P[loud].mean(0)
        bd={b:10*np.log10(Pl[(fr>=lo)&(fr<hi)].sum()) for b,(lo,hi) in bands.items()}
        tot=10*np.log10(Pl[(fr>=50)].sum())
        for b in bands:f[b]=bd[b]-tot
        f['tilt']=np.polyfit(np.log10(fr[(fr>=100)&(fr<7000)]),10*np.log10(Pl[(fr>=100)&(fr<7000)]),1)[0]
        f['lo_minus_hi']=bd['b_lo']-bd['b_hi']
        cen=(P*fr).sum(1)/P.sum(1);f['centroid_loud']=cen[loud].mean()
        # envelope sharpness: frame-to-frame dB changes (close mic = sharp, reverberant = smeared)
        d=np.diff(edb);f['env_rise_p90']=np.percentile(d,90);f['env_fall_p10']=np.percentile(d,10)
        # decay: median slope over falling runs from local peaks (dB per 10ms)
        f['dyn_range']=np.percentile(edb,95)-np.percentile(edb,10)
        # modulation depth at speech rate (2-8 Hz) of the envelope
        env=10**(edb/20);env=env-env.mean()
        if len(env)>=64:
            M=np.abs(np.fft.rfft(env*np.hanning(len(env))))**2;mf=np.fft.rfftfreq(len(env),hop/sr)
            f['mod_2_8']=10*np.log10(M[(mf>=2)&(mf<8)].sum()/(M[(mf>=0.5)].sum()+1e-12)+1e-12)
        # spectral flux (sharp onsets)
        Lp=np.log(P);f['flux']=np.mean(np.maximum(np.diff(Lp,axis=0),0).sum(1))/P.shape[1]
        out.append(f)
    print(k,len(C),round(time.time()-t0),'s',flush=True);del x
json.dump(out,open(sys.argv[1],'w'),default=float)
