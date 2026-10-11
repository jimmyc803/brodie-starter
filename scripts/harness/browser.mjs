import { chromium, expect } from '@playwright/test';
import assert from 'node:assert/strict';
import { readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';

export async function runBrowserTests({db,gateway,url,repoRoot,artifacts,modeFile,callsFile,results=[]}) {
  const token='harness_coach_tristan_0001';
  const coach=(await db.query('insert into coaches(name,share_token) values($1,$2) returning id',['Tristan',token])).rows[0];
  const client=(await db.query('insert into clients(coach_id,name) values($1,$2) returning id',[coach.id,'Ryan'])).rows[0];
  const browser=await chromium.launch({headless:true});
  let context;
  try {
  context=await browser.newContext({viewport:{width:1440,height:1100}});
  await context.tracing.start({screenshots:true,snapshots:true});
  const page=await context.newPage();
  const errors=[]; page.on('pageerror',error=>errors.push(error.message));
  const check=async(name,fn)=>{await fn();results.push({name,status:'passed'});console.log(`PASS browser: ${name}`);};
  try {
    await page.goto(`${url}/c/${token}/program`);
    await expect(page.getByRole('heading',{name:'Upload your program'})).toBeVisible({timeout:90000});
    await check('responsive styled desktop and mobile forms',async()=>{
      const button=page.getByRole('button',{name:'Upload & parse program'});
      const grid=page.locator('div.grid.gap-6');
      assert.equal(await grid.evaluate(el=>getComputedStyle(el).display),'grid');
      assert.equal((await grid.evaluate(el=>getComputedStyle(el).gridTemplateColumns)).split(' ').length,2);
      assert.notEqual(await button.evaluate(el=>getComputedStyle(el).backgroundColor),'rgba(0, 0, 0, 0)');
      assert.equal(await button.evaluate(el=>getComputedStyle(el).paddingLeft),'24px');
      await page.screenshot({path:path.join(artifacts,'desktop-empty.png'),fullPage:true});
      await page.setViewportSize({width:390,height:844});
      assert.equal((await grid.evaluate(el=>getComputedStyle(el).gridTemplateColumns)).split(' ').length,1);
      assert(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth));
      await page.screenshot({path:path.join(artifacts,'mobile-program.png'),fullPage:true});
      await page.setViewportSize({width:1440,height:1100});
    });
    await check('PDF upload through UI, actual parser, storage and SQL',async()=>{
      await page.getByLabel('Program PDF').setInputFiles(path.join(repoRoot,'db/fixtures/sample_program.pdf'));
      await page.getByRole('button',{name:'Upload & parse program'}).click();
      await expect(page.getByRole('status')).toContainText('Program saved',{timeout:60000});
      await expect(page.getByRole('heading',{name:"Tristan's Three-Day Foundation Program"})).toBeVisible();
      const programs=(await db.query('select * from programs where coach_id=$1',[coach.id])).rows;
      assert.equal(programs.length,1); assert.equal(gateway.objects.size,1);
      assert.deepEqual(gateway.objects.get(programs[0].pdf_path),await readFile(path.join(repoRoot,'db/fixtures/sample_program.pdf')));
      const days=(await db.query('select * from program_days where program_id=$1 order by day_number',[programs[0].id])).rows;
      assert.equal(days.length,3);
      const expected=JSON.parse(await readFile(path.join(repoRoot,'db/fixtures/sample_program.expected.json'),'utf8'));
      assert.deepEqual(days.map(d=>({day_number:d.day_number,title:d.title,exercises:d.exercises})),expected.days);
      await expect(page.getByText('Manual tracking',{exact:true})).toHaveCount(4);
      assert.equal(JSON.parse((await readFile(callsFile,'utf8')).trim()).mode,'success');
      await page.screenshot({path:path.join(artifacts,'program-upload.png'),fullPage:true});
    });
    await check('assignment UI persists and replaces active assignment',async()=>{
      const days=(await db.query('select d.id from program_days d join programs p on p.id=d.program_id where p.coach_id=$1 order by day_number',[coach.id])).rows;
      for(const day of days.slice(0,2)) {
        await page.getByLabel('Client',{exact:true}).selectOption(client.id);
        await page.getByLabel('Training day',{exact:true}).selectOption(day.id);
        await page.getByRole('button',{name:'Assign training day',exact:true}).click();
        await expect(page.getByRole('status').filter({hasText:'Day assigned'})).toBeVisible();
        await expect.poll(async()=> (await db.query('select program_day_id from assignments where client_id=$1 and active',[client.id])).rows).toEqual([{program_day_id:day.id}]);
      }
      const rows=(await db.query('select active from assignments where client_id=$1',[client.id])).rows;
      assert.equal(rows.length,2); assert.equal(rows.filter(r=>r.active).length,1);
      await page.screenshot({path:path.join(artifacts,'day-assigned.png'),fullPage:true});
    });
    await check('invalid PDF rejected before storage',async()=>{
      const before=gateway.requests.length;
      await page.getByLabel('Program PDF').setInputFiles({name:'invalid.pdf',mimeType:'application/pdf',buffer:Buffer.from('this is not a pdf')});
      await page.getByRole('button',{name:'Upload & parse program'}).click();
      await expect(page.locator('form [role=alert]')).toHaveText('Choose a valid PDF document.');
      assert.equal(gateway.objects.size,1);
      assert(!gateway.requests.slice(before).some(r=>r.path.startsWith('/storage/')));
    });
    await check('oversized PDF rejected by client and server',async()=>{
      const buffer=Buffer.alloc(3*1024*1024+1);buffer.write('%PDF-1.4');
      await page.getByLabel('Program PDF').setInputFiles({name:'oversized.pdf',mimeType:'application/pdf',buffer});
      assert.equal(await page.getByLabel('Program PDF').evaluate(el=>el.validationMessage),'Choose a PDF no larger than 3 MB.');
      await page.getByLabel('Program PDF').evaluate(el=>el.setCustomValidity(''));
      await page.getByRole('button',{name:'Upload & parse program'}).click();
      await expect(page.locator('form [role=alert]')).toHaveText('Choose a PDF between 8 bytes and 3 MB.');
      assert.equal(gateway.objects.size,1);
    });
    await check('provider failure removes stored PDF, preserves existing program',async()=>{
      await writeFile(modeFile,'failure');
      await page.getByLabel('Program PDF').setInputFiles(path.join(repoRoot,'db/fixtures/sample_program.pdf'));
      await page.getByRole('button',{name:'Upload & parse program'}).click();
      await expect(page.locator('form [role=alert]')).toContainText('Program could not be saved. Check the parser');
      assert.equal(gateway.objects.size,1);
      assert.equal((await db.query('select count(*)::int n from programs where coach_id=$1',[coach.id])).rows[0].n,1);
      assert(gateway.requests.some(r=>r.method==='DELETE' && r.path.startsWith('/storage/')));
      await writeFile(modeFile,'success');
    });
    await check('unknown coach reveals no upload controls',async()=>{
      await page.goto(`${url}/c/harness_unknown_coach_0001/program`);
      await expect(page.getByText('This page could not be found.')).toBeVisible();
      await expect(page.getByLabel('Program PDF')).toHaveCount(0);
    });
    assert.deepEqual(errors,[]);
  } finally {
    await context.tracing.stop({path:path.join(artifacts,'browser-trace.zip')});
  }
  return results;
  } finally { await browser.close(); }
}
