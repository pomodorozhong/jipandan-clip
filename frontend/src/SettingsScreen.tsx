export default function SettingsScreen({ detectLeadingSilence, showOriginalStart,
  onDetectLeadingSilenceChange, onShowOriginalStartChange }: {
  detectLeadingSilence: boolean;
  showOriginalStart: boolean;
  onDetectLeadingSilenceChange: (enabled: boolean) => void;
  onShowOriginalStartChange: (enabled: boolean) => void;
}) {
  return <main className="panel-scroll mx-auto w-full max-w-3xl flex-1 overflow-auto px-5 py-8 md:px-8">
    <div className="mb-6">
      <div>
        <p className="accent mb-2 text-xs font-semibold uppercase tracking-[.16em]">Preferences</p>
        <h1 className="text-3xl font-semibold">Settings</h1>
        <p className="subtle mt-2 text-sm">These settings are saved in this browser.</p>
      </div>
    </div>

    <section className="surface rounded-2xl p-5">
      <h2 className="mb-4 text-lg font-semibold">Clip timing</h2>
      <label className="flex cursor-pointer items-start gap-3 border-b line pb-4">
        <input type="checkbox" checked={detectLeadingSilence}
          onChange={(event) => onDetectLeadingSilenceChange(event.target.checked)} className="mt-1" />
        <span>
          <strong className="block text-sm">Detect leading silence</strong>
          <span className="subtle mt-1 block text-sm">Analyze clips that still use their SRT start in the background and move them to the first sustained audio activity. You can restore the SRT start from the nudging screen.</span>
        </span>
      </label>
      <label className="flex cursor-pointer items-start gap-3 pt-4">
        <input type="checkbox" checked={showOriginalStart}
          onChange={(event) => onShowOriginalStartChange(event.target.checked)} className="mt-1" />
        <span>
          <strong className="block text-sm">Show original start time on waveform</strong>
          <span className="subtle mt-1 block text-sm">Draw the SRT start as a separate marker in the waveform views.</span>
        </span>
      </label>
    </section>
  </main>;
}
