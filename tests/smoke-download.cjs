/* GitHub Actions browser smoke test: real UI -> mock XYZ HTTP server -> ZIP download. */
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('/tmp/offline-map-playwright/node_modules/playwright-core');

const tile = fs.readFileSync(path.join(process.cwd(), 'changeTiles/13367.png'));
const srv = http.createServer((req, res) => {
  if (!/^\/tiles\/\d+\/\d+\/\d+\.png(?:\?.*)?$/.test(req.url || '')) {
    res.writeHead(404); res.end('not found'); return;
  }
  res.writeHead(200, {
    'Content-Type': 'image/png',
    'Access-Control-Allow-Origin': '*',
    'Cache-Control': 'no-store'
  });
  res.end(tile);
});
function listen(server, port) {
  return new Promise((resolve,reject) => server.once('error', reject).listen(port,'127.0.0.1',resolve));
}
async function action(page, label) {
  await page.locator('.config-panel .el-select').last().click();
  await page.locator('.el-select-dropdown__item:visible').filter({hasText:label}).first().click();
  await page.getByRole('button',{name:'触发操作'}).click();
}
(async () => {
  await listen(srv,4242);
  const browser = await chromium.launch({
    headless:true,
    executablePath:'/usr/bin/google-chrome',
    args:['--no-sandbox','--disable-dev-shm-usage']
  });
  try {
    const context = await browser.newContext({acceptDownloads:true});
    const page = await context.newPage();
    const pageErrors = [];
    page.on('pageerror',e=>pageErrors.push(String(e)));
    await page.goto('http://127.0.0.1:5173/',{waitUntil:'domcontentloaded',timeout:30000});
    await page.waitForFunction('window.theMap && window.theMap.canvas',{timeout:20000});
    console.log('UI_LOADED', await page.title());
    console.log('INITIAL_MAP', await page.evaluate(() => ({
      zoom:window.theMap.zoom, tileUrl:window.theMap.tileUrl,
      canvas:{width:window.theMap.canvas.width,height:window.theMap.canvas.height}
    })));
    const defaultTileProbe = await page.evaluate(async()=>{
      const map=window.theMap;
      const t=map.getTileList(map.getBounds(),map.zoom)[0];
      if(!t) return {error:'No visible XYZ tiles'};
      try {
        const resp=await fetch(t.url,{signal:AbortSignal.timeout(10000)});
        return {url:t.url,httpStatus:resp.status,contentType:resp.headers.get('content-type'),corsAccessible:true};
      } catch(e) {
        return {url:t.url,error:String(e),corsAccessible:false};
      }
    });
    console.log('DEFAULT_TILE_FETCH', JSON.stringify(defaultTileProbe));
    // Select an isolated test tile source with CORS enabled.
    const testUrl='http://127.0.0.1:4242/tiles/{z}/{y}/{x}.png';
    const input=page.locator('input[placeholder="请输入瓦片地址"]');
    await input.fill(testUrl);
    await input.press('Tab');
    await action(page,'重绘地图');
    await page.waitForFunction(u => window.theMap?.tileUrl===u,testUrl,{timeout:10000}).catch(async()=>{
      const value=await page.evaluate(()=>window.theMap.tileUrl);
      throw new Error('Configured tile URL not applied: '+value);
    });
    await action(page,'获取当前地图范围');
    await page.waitForTimeout(500);
    const tilesVisible = await page.evaluate(()=>Object.values(window.theMap.cacheTiles).filter(Boolean).length);
    console.log('MOCK_TILES_RENDERED',tilesVisible);
    if (tilesVisible === 0) throw new Error('No mock tiles rendered on map canvas');
    await page.screenshot({path:'/tmp/offline-map-screenshot.png',fullPage:true});
    page.once('dialog',dialog=>dialog.accept());
    const downloadPromise=page.waitForEvent('download',{timeout:120000});
    await action(page,'下载地图瓦片');
    const download=await downloadPromise;
    await download.saveAs('/tmp/offline-map-tiles.zip');
    console.log('ZIP_DOWNLOADED',download.suggestedFilename(),fs.statSync('/tmp/offline-map-tiles.zip').size);
    console.log('BROWSER_PAGE_ERRORS', JSON.stringify(pageErrors));
    if(pageErrors.length) throw new Error('Page errors: '+pageErrors.join('; '));
    console.log('SMOKE_TEST_PASSED');
  } finally {
    await browser.close();
    await new Promise(resolve=>srv.close(resolve));
  }
})().catch(e=>{console.error('SMOKE_TEST_FAILED',e.stack||e);process.exitCode=1;});
