const { chromium, devices } = require('playwright');
(async()=>{
 const browser=await chromium.launch({headless:true});
 const failures=[];
 for(const device of ['Desktop Chrome','iPhone 13']){
  const context=await browser.newContext(device==='Desktop Chrome'?{viewport:{width:1365,height:900}}:{...devices['iPhone 13']});
  const page=await context.newPage();const errors=[];
  page.on('console',msg=>{if(msg.type()==='error'&&msg.text().includes('metals'))errors.push('console '+msg.text())});
  page.on('response',res=>{if(res.url().includes('/api/metals-analysis'))console.log(device+' METALS HTTP '+res.status()+' '+res.url())});
  page.on('pageerror',e=>errors.push(e.message));
  page.on('requestfailed',req=>{if(req.url().includes('/api/metals-analysis'))errors.push('METALS REQUEST '+req.failure()?.errorText+' '+req.url())});
  const url=process.env.ATLAS_TEST_URL||'https://farham2021.github.io/-ATLAS-AI-ALITAL/';
  const response=await page.goto(url,{waitUntil:'domcontentloaded',timeout:45000});
  if(!response?.ok())failures.push(device+' page HTTP '+response?.status());
  for(const id of ['nav','us','news','charts','metals','metalSymbol','metalTf','metalAnalyze','metalAnalysis','usSymbol','newsSymbol','chartSymbol','usChartBtn','newsLoad','chartShow']) {
   if(await page.locator('#'+id).count()!==1)failures.push(device+' missing '+id);
  }
  await page.waitForTimeout(4000);
  for(const [tab,button,output] of [['metals','metalAnalyze','metalAnalysis'],['us','usChartBtn','usChart'],['charts','chartShow','tvChart'],['news','newsLoad','newsRows']]){
   const all=page.locator('#atlas-ui-groups button').first();
   if(await all.count()){await all.click();await page.waitForFunction(()=>[...document.querySelectorAll('#nav button')].every(b=>!b.hidden),{timeout:5000}).catch(()=>{});}
   const tabButton=page.locator('#nav button[data-tab="'+tab+'"]');
   await tabButton.evaluate(button=>{button.hidden=false;button.click()});
   await page.locator('#'+tab).waitFor({state:'visible',timeout:10000});
   await page.locator('#'+button).click();
   await page.waitForTimeout(2500);
   if(!(await page.locator('#'+output).isVisible()))failures.push(device+' hidden '+output);
   if(tab==='metals'){await page.waitForTimeout(1000);const txt=await page.locator('#metalAnalysis').innerText();if(!txt.includes('XAUUSD')&&!txt.includes('XAGUSD'))failures.push(device+' metals analysis missing selected symbol: '+txt.slice(0,180));if(txt.includes('ناموفق')||txt.includes('unavailable'))failures.push(device+' metals API failed: '+txt.slice(0,200));}
  }
  const api=await page.request.get('https://onnyytvtfcvlzkagijzz.supabase.co/functions/v1/atlas-web/api/us-markets');
  if(!api.ok())failures.push(device+' US API '+api.status());
  const metalApi=await page.request.get('https://onnyytvtfcvlzkagijzz.supabase.co/functions/v1/atlas-web/api/metals-analysis?symbol=XAUUSD',{headers:{Origin:'http://127.0.0.1:8765'}}).catch(e=>({error:e.message}));
  if(metalApi.error)failures.push(device+' metal API network '+metalApi.error);
  else {const body=await metalApi.text();console.log(device+' METAL API direct '+metalApi.status()+' CORS '+metalApi.headers()['access-control-allow-origin']+' '+body.slice(0,240));if(!metalApi.ok())failures.push(device+' metal API HTTP '+metalApi.status()+' '+body.slice(0,180));}
  const news=await page.request.get('https://onnyytvtfcvlzkagijzz.supabase.co/functions/v1/atlas-web/api/crypto-news?symbol=BTC');
  if(!news.ok()&&news.status()!==503)failures.push(device+' news API '+news.status());
  else {const data=await news.json();if(!Array.isArray(data.items))failures.push(device+' malformed news response')}
  await page.locator('#language').selectOption('en');await page.waitForTimeout(1500);
  const localeCheck=await page.evaluate(()=>({en:document.documentElement.lang,utc:fmt('2026-11-13T16:26:08Z'),fa:(()=>{const saved=currentLang;currentLang='fa';const v=fmt('2026-11-13T16:26:08Z');currentLang=saved;return v})()}));
  if(localeCheck.en!=='en'||!localeCheck.utc.includes('2026')||!localeCheck.utc.includes('UTC')||!localeCheck.fa.includes('تهران'))failures.push(device+' locale '+JSON.stringify(localeCheck));
  await page.screenshot({path:'atlas-'+device.replaceAll(' ','-')+'.png',fullPage:true});
  failures.push(...errors.filter(x=>!/(TradingView|widget|network|fetch|Failed to load)/i.test(x)).map(x=>device+' JS '+x));
  await context.close();
 }
 await browser.close();
 if(failures.length){console.error(failures.join('\n'));process.exit(1)}
 console.log('Desktop and iPhone emulation passed, including API and UI smoke tests');
})().catch(e=>{console.error(e);process.exit(1)});
