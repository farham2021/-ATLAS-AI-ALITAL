const { chromium, devices } = require('playwright');
(async () => {
 const browser=await chromium.launch({headless:true}); const failures=[];
 for(const device of ['Desktop Chrome','iPhone 13']){
  const context=await browser.newContext(device==='Desktop Chrome'?{viewport:{width:1365,height:900}}:{...devices['iPhone 13']});
  const page=await context.newPage(); const errors=[];
  page.on('pageerror',e=>errors.push(e.stack||e.message));
  const response=await page.goto(process.env.ATLAS_TEST_URL||'http://127.0.0.1:8765/',{waitUntil:'domcontentloaded',timeout:45000});
  if(!response?.ok())failures.push(device+' root HTTP '+response?.status());
  for(const id of ['atlas-main-menu','web3-markets','iran-panel','opportunity-lab','crypto-top50-panel','metals-panel','us-panel','news-panel','chart-panel']){
   if(await page.locator('#'+id).count()!==1)failures.push(device+' root missing #'+id);
  }
  await page.waitForTimeout(1200);
  failures.push(...errors.map(e=>device+' JS '+e));
  await page.screenshot({path:'atlas-root-'+device.replaceAll(' ','-')+'.png',fullPage:true});
  await context.close();
 }
 await browser.close();
 if(failures.length){console.error(failures.join('\n'));process.exit(1)}
 console.log('Root dashboard desktop and mobile structure/runtime smoke passed');
})().catch(e=>{console.error(e);process.exit(1)});
