const { chromium, devices } = require('playwright');
(async()=>{
 const browser=await chromium.launch({headless:true});
 const failures=[];
 for(const device of ['Desktop Chrome','iPhone 13']){
  const context=await browser.newContext(device==='Desktop Chrome'?{viewport:{width:1365,height:900}}:{...devices['iPhone 13']});
  const page=await context.newPage();const errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  const url='https://farham2021.github.io/-ATLAS-AI-ALITAL/';
  const response=await page.goto(url,{waitUntil:'domcontentloaded',timeout:45000});
  if(!response?.ok())failures.push(device+' page HTTP '+response?.status());
  for(const id of ['nav','us','news','charts','usSymbol','newsSymbol','chartSymbol','usChartBtn','newsLoad','chartShow']) {
   if(await page.locator('#'+id).count()!==1)failures.push(device+' missing '+id);
  }
  await page.waitForTimeout(4000);
  for(const [tab,button,output] of [['us','usChartBtn','usChart'],['charts','chartShow','tvChart'],['news','newsLoad','newsRows']]){
   await page.locator('#nav button[data-tab="'+tab+'"]').click();
   await page.locator('#'+button).click();
   await page.waitForTimeout(2500);
   if(!(await page.locator('#'+output).isVisible()))failures.push(device+' hidden '+output);
  }
  const api=await page.request.get('https://onnyytvtfcvlzkagijzz.supabase.co/functions/v1/atlas-web/api/us-markets');
  if(!api.ok())failures.push(device+' US API '+api.status());
  const news=await page.request.get('https://onnyytvtfcvlzkagijzz.supabase.co/functions/v1/atlas-web/api/crypto-news?symbol=BTC');
  if(!news.ok())failures.push(device+' news API '+news.status());
  else {const data=await news.json();if(!Array.isArray(data.items))failures.push(device+' malformed news response')}
  await page.screenshot({path:'atlas-'+device.replaceAll(' ','-')+'.png',fullPage:true});
  failures.push(...errors.map(x=>device+' JS '+x));
  await context.close();
 }
 await browser.close();
 if(failures.length){console.error(failures.join('\n'));process.exit(1)}
 console.log('Desktop and iPhone emulation passed, including API and UI smoke tests');
})().catch(e=>{console.error(e);process.exit(1)});
