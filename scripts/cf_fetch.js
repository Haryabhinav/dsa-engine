// Paste into the DevTools console on any codeforces.com tab while LOGGED IN.
// It reads only YOUR OWN submissions, one every 400ms, and downloads one JSON.
// Nothing is sent anywhere: the file is saved locally by your browser.
(async () => {
  const TARGETS = [{"cid": 2178,"idx": "C","role": "buggy","sid": 375299665},{"cid": 2178,"idx": "C","role": "fixed","sid": 375301495},{"cid": 2228,"idx": "C1","role": "buggy","sid": 374950734},{"cid": 2228,"idx": "C1","role": "fixed","sid": 374951356},{"cid": 2228,"idx": "B","role": "buggy","sid": 374767273},{"cid": 2228,"idx": "B","role": "fixed","sid": 374784404},{"cid": 2228,"idx": "A","role": "buggy","sid": 374754479},{"cid": 2228,"idx": "A","role": "fixed","sid": 374777829},{"cid": 2126,"idx": "D","role": "buggy","sid": 361734970},{"cid": 2126,"idx": "D","role": "fixed","sid": 374246079},{"cid": 2202,"idx": "B","role": "buggy","sid": 374242363},{"cid": 2202,"idx": "B","role": "fixed","sid": 374242735},{"cid": 2210,"idx": "C1","role": "buggy","sid": 374241411},{"cid": 2210,"idx": "C1","role": "fixed","sid": 374241675},{"cid": 2084,"idx": "B","role": "buggy","sid": 367150195},{"cid": 2084,"idx": "B","role": "fixed","sid": 367151343},{"cid": 2208,"idx": "B","role": "buggy","sid": 366683807},{"cid": 2208,"idx": "B","role": "fixed","sid": 366687146},{"cid": 2208,"idx": "A","role": "buggy","sid": 366647846},{"cid": 2208,"idx": "A","role": "fixed","sid": 366653383},{"cid": 2182,"idx": "B","role": "buggy","sid": 363529673},{"cid": 2182,"idx": "B","role": "fixed","sid": 363535763},{"cid": 2183,"idx": "A","role": "buggy","sid": 363257752},{"cid": 2183,"idx": "A","role": "fixed","sid": 363259365},{"cid": 2195,"idx": "B","role": "buggy","sid": 363073134},{"cid": 2195,"idx": "B","role": "fixed","sid": 363094396},{"cid": 2195,"idx": "A","role": "buggy","sid": 363056759},{"cid": 2195,"idx": "A","role": "fixed","sid": 363080925},{"cid": 2185,"idx": "D","role": "buggy","sid": 362877595},{"cid": 2185,"idx": "D","role": "fixed","sid": 362880556},{"cid": 2191,"idx": "B","role": "buggy","sid": 362797108},{"cid": 2191,"idx": "B","role": "fixed","sid": 362798201},{"cid": 2185,"idx": "C","role": "buggy","sid": 362754491},{"cid": 2185,"idx": "C","role": "fixed","sid": 362787779},{"cid": 2193,"idx": "A","role": "buggy","sid": 362302125},{"cid": 2193,"idx": "A","role": "fixed","sid": 362302353},{"cid": 2193,"idx": "B","role": "buggy","sid": 362123481},{"cid": 2193,"idx": "B","role": "fixed","sid": 362123654},{"cid": 2184,"idx": "C","role": "buggy","sid": 362014461},{"cid": 2184,"idx": "C","role": "fixed","sid": 362014542},{"cid": 2107,"idx": "B","role": "buggy","sid": 361325821},{"cid": 2107,"idx": "B","role": "fixed","sid": 361328398},{"cid": 2153,"idx": "B","role": "buggy","sid": 360353756},{"cid": 2153,"idx": "B","role": "fixed","sid": 360353921},{"cid": 2122,"idx": "B","role": "buggy","sid": 359216856},{"cid": 2122,"idx": "B","role": "fixed","sid": 359217189},{"cid": 2170,"idx": "B","role": "buggy","sid": 359203434},{"cid": 2170,"idx": "B","role": "fixed","sid": 359205663},{"cid": 2126,"idx": "C","role": "buggy","sid": 359189133},{"cid": 2126,"idx": "C","role": "fixed","sid": 359189743},{"cid": 2174,"idx": "A","role": "buggy","sid": 359017587},{"cid": 2174,"idx": "A","role": "fixed","sid": 359018013},{"cid": 2071,"idx": "B","role": "buggy","sid": 358930348},{"cid": 2071,"idx": "B","role": "fixed","sid": 358933421},{"cid": 2164,"idx": "A","role": "buggy","sid": 358425441},{"cid": 2164,"idx": "A","role": "fixed","sid": 358426643},{"cid": 2160,"idx": "B","role": "buggy","sid": 358027435},{"cid": 2160,"idx": "B","role": "fixed","sid": 358027695},{"cid": 2173,"idx": "B","role": "buggy","sid": 357869811},{"cid": 2173,"idx": "B","role": "fixed","sid": 357869976},{"cid": 1906,"idx": "A","role": "buggy","sid": 357865714},{"cid": 1906,"idx": "A","role": "fixed","sid": 357866004},{"cid": 2002,"idx": "B","role": "buggy","sid": 357861434},{"cid": 2002,"idx": "B","role": "fixed","sid": 357863558},{"cid": 2148,"idx": "D","role": "buggy","sid": 356899905},{"cid": 2148,"idx": "D","role": "fixed","sid": 356900623},{"cid": 2167,"idx": "D","role": "buggy","sid": 356449654},{"cid": 2167,"idx": "D","role": "fixed","sid": 356449980},{"cid": 2176,"idx": "A","role": "buggy","sid": 355703850},{"cid": 2176,"idx": "A","role": "fixed","sid": 355879322}];
  const out = [];
  const csrf = document.querySelector('meta[name="X-Csrf-Token"]')?.content
            || document.querySelector('input[name="csrf_token"]')?.value;
  console.log('csrf token found:', !!csrf, '| targets:', TARGETS.length);
  for (let i = 0; i < TARGETS.length; i++) {
    const t = TARGETS[i];
    try {
      const body = new URLSearchParams({ submissionId: String(t.sid), csrf_token: csrf || '' });
      const r = await fetch('/data/submitSource', {
        method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded',
                   'X-Requested-With': 'XMLHttpRequest' },
        body
      });
      const j = await r.json();
      out.push({ ...t, source: j.source || '', ok: !!j.source });
      console.log(`[${i + 1}/${TARGETS.length}] ${t.cid}${t.idx} ${t.role} ${(j.source || '').length} chars`);
    } catch (e) {
      out.push({ ...t, source: '', ok: false, error: String(e) });
      console.warn('failed', t.sid, e);
    }
    await new Promise(s => setTimeout(s, 400));   // be polite to the server
  }
  const blob = new Blob([JSON.stringify(out, null, 2)], { type: 'application/json' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'cf_sources.json';
  a.click();
  console.log('DONE — fetched', out.filter(x => x.ok).length, 'of', out.length);
})();
