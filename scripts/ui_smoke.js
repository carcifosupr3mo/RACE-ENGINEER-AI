const { chromium } = require('playwright');
(async()=>{const b=await chromium.launch();const p=await b.newPage({viewport:{width:1280,height:800},deviceScaleFactor:1});
const errs=[];p.on('pageerror',e=>errs.push(String(e)));p.on('console',m=>{if(m.type()==='error')errs.push(m.text())});
await p.goto((process.argv[2]||'http://127.0.0.1:8765/'));await p.waitForTimeout(3000);
console.log('state:',await p.textContent('#state'),'| speed:',await p.textContent('#speed'),'| syn banner visible:',await p.isVisible('#syn'));
console.log('errors:',JSON.stringify(errs));
await p.screenshot({path:''+(process.argv[3]||'ui_smoke.png')+''});await b.close()})();
