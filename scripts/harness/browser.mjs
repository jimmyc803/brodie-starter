import { chromium, expect } from '@playwright/test';
import assert from 'node:assert/strict';
import { readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
const execFileAsync = promisify(execFile);

export async function runBrowserTests({db,gateway,url,repoRoot,artifacts,modeFile,callsFile,results=[],acquireBrowser=create=>create()}) {
  const token='harness_coach_tristan_0001';
  const coach=(await db.query('insert into coaches(name,share_token) values($1,$2) returning id',['Tristan',token])).rows[0];
  const client=(await db.query('insert into clients(coach_id,name) values($1,$2) returning id',[coach.id,'Ryan'])).rows[0];
  const browser=await acquireBrowser(()=>chromium.launch({headless:true}));
  let context;
  try {
  context=await browser.newContext({viewport:{width:1440,height:1100}});
  await context.tracing.start({screenshots:true,snapshots:true});
  const page=await context.newPage();
  const errors=[]; page.on('pageerror',error=>errors.push(error.message));
  const check=async(name,fn)=>{await fn();results.push({name,status:'passed'});console.log(`PASS browser: ${name}`);};
  try {
    await page.goto(`${url}/c/${token}/program`);
    await expect(page.getByRole('heading',{name:'Upload a program'})).toBeVisible({timeout:90000});
    await check('responsive styled desktop and mobile forms',async()=>{
      const button=page.getByRole('button',{name:'Upload & parse program'});
      const grid=page.locator('div.grid.gap-6');
      assert.equal(await grid.evaluate(el=>getComputedStyle(el).display),'grid');
      assert.equal((await grid.evaluate(el=>getComputedStyle(el).gridTemplateColumns)).split(' ').length,2);
      assert.notEqual(await button.evaluate(el=>getComputedStyle(el).backgroundColor),'rgba(0, 0, 0, 0)');
      assert.equal(await button.evaluate(el=>getComputedStyle(el).paddingLeft),'20px');
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
    await check('assignment feedback survives reload',async()=>{
      await page.reload();
      const current=page.getByRole('region',{name:'Current assignments'});
      await expect(current).toContainText('Ryan');
      const assigned=(await db.query('select d.day_number,d.title from assignments a join program_days d on d.id=a.program_day_id where a.client_id=$1 and a.active',[client.id])).rows[0];
      await expect(current).toContainText(`Day ${assigned.day_number}: ${assigned.title}`);
      await expect(page.getByRole('status').filter({hasText:'Day assigned'})).toHaveCount(0);
    });
    const forgeAssignment=async(clientId,dayId)=>{
      const before=(await db.query('select * from assignments order by id')).rows;
      const requestStart=gateway.requests.length;
      // Attack the actual action through DOM form controls, bypassing the visible option allowlist.
      for (const [label,value] of [['Client',clientId],['Training day',dayId]]) {
        const select=page.getByLabel(label,{exact:true});
        await select.evaluate((el,value)=>{const option=new Option('Forged option',value);el.append(option);el.disabled=false;},value);
        await select.selectOption(value);
      }
      await page.getByRole('button',{name:'Assign training day',exact:true}).click();
      await expect(page.locator('form [role=alert]')).toContainText('Assignment could not be saved');
      assert(gateway.requests.slice(requestStart).some(r=>r.method==='POST' && r.path==='/rest/v1/rpc/assign_coach_program_day'));
      assert.deepEqual((await db.query('select * from assignments order by id')).rows,before);
      await page.reload();
      await expect(page.getByRole('heading',{name:'Upload a program'})).toBeVisible();
    };
    await check('forged cross-coach client and day rejected atomically',async()=>{
      const foreignCoach=(await db.query('insert into coaches(name) values($1) returning id',['Private Other Coach'])).rows[0];
      const foreignClient=(await db.query('insert into clients(coach_id,name) values($1,$2) returning id',[foreignCoach.id,'Private Other Client'])).rows[0];
      const foreignProgram=(await db.query('insert into programs(coach_id,title) values($1,$2) returning id',[foreignCoach.id,'Private Other Program'])).rows[0];
      const foreignDay=(await db.query('insert into program_days(program_id,day_number,title,exercises) values($1,1,$2,$3) returning id',[foreignProgram.id,'Private Other Day',JSON.stringify([{exercise_key:'squat',name:'Squat',sets:1,reps:10,notes:'',supported:true}])])).rows[0];
      const ownedDay=(await db.query('select program_day_id from assignments where client_id=$1 and active',[client.id])).rows[0].program_day_id;
      await db.query('insert into assignments(client_id,program_day_id) values($1,$2)',[foreignClient.id,foreignDay.id]);
      await page.reload();
      await expect(page.getByText('Private Other Client',{exact:true})).toHaveCount(0);
      await expect(page.getByText('Private Other Day',{exact:true})).toHaveCount(0);
      await forgeAssignment(foreignClient.id,ownedDay);
      await forgeAssignment(client.id,foreignDay.id);
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
    for (const mode of ['failure','malformed-json','invalid-schema']) {
      await check(`${mode} removes uploaded PDF and preserves all persisted rows`,async()=>{
        await page.reload();
        await expect(page.getByRole('heading',{name:'Upload a program'})).toBeVisible();
        const beforePrograms=(await db.query('select * from programs order by id')).rows;
        const beforeDays=(await db.query('select * from program_days order by id')).rows;
        const beforeObjects=[...gateway.objects.entries()];
        const requestStart=gateway.requests.length;
        await writeFile(modeFile,mode);
        await page.getByLabel('Program PDF').setInputFiles(path.join(repoRoot,'db/fixtures/sample_program.pdf'));
        await page.getByRole('button',{name:'Upload & parse program'}).click();
        await expect(page.locator('form [role=alert]')).toContainText('Program could not be saved. Check the parser');
        assert.deepEqual([...gateway.objects.entries()],beforeObjects);
        assert.deepEqual((await db.query('select * from programs order by id')).rows,beforePrograms);
        assert.deepEqual((await db.query('select * from program_days order by id')).rows,beforeDays);
        const recent=gateway.requests.slice(requestStart);
        assert(recent.some(r=>r.method==='POST' && r.path.startsWith('/storage/')));
        assert(recent.some(r=>r.method==='DELETE' && r.path.startsWith('/storage/')));
        assert(!recent.some(r=>r.path==='/rest/v1/rpc/save_coach_program'));
        const calls=(await readFile(callsFile,'utf8')).trim().split('\n').map(JSON.parse);
        assert.equal(calls.at(-1).mode,mode);
      });
    }
    await check('forged provider support claims become unassignable manual-only day',async()=>{
      await writeFile(modeFile,'forged-support');
      await page.getByLabel('Program PDF').setInputFiles(path.join(repoRoot,'db/fixtures/sample_program.pdf'));
      await page.getByRole('button',{name:'Upload & parse program'}).click();
      await expect(page.getByRole('status')).toContainText('Program saved');
      const program=(await db.query('select id from programs where coach_id=$1 and title=$2',[coach.id,'Manual-only adversarial program'])).rows;
      assert.equal(program.length,1);
      const days=(await db.query('select * from program_days where program_id=$1',[program[0].id])).rows;
      assert.equal(days.length,1);
      assert.deepEqual(days[0].exercises,[{name:'Bench press',sets:3,reps:10,notes:'Manual exercise',exercise_key:null,supported:false}]);
      assert.equal(gateway.objects.size,2);
      assert.equal((await db.query('select count(*)::int n from programs where coach_id=$1',[coach.id])).rows[0].n,2);
      await expect(page.getByRole('heading',{name:'Bench-only day'})).toBeVisible();
      await expect(page.getByLabel('Training day',{exact:true}).locator(`option[value="${days[0].id}"]`)).toHaveCount(0);
      await forgeAssignment(client.id,days[0].id);
      await writeFile(modeFile,'success');
    });
    await check('browser assignments load through real Python HTTP worker plan loader',async()=>{
      const python=process.env.HARNESS_PYTHON || path.join(repoRoot,'.venv/bin/python');
      const load=async()=>{
        const {stdout}=await execFileAsync(python,['-c',
          'import json,sys; from facetime.plan_loader import load_assignment; result=load_assignment(sys.argv[1]); assert result is not None; print("HARNESS_PLAN="+json.dumps(result))',client.id],{
          cwd:repoRoot,timeout:30000,maxBuffer:1024*1024,
          env:{PATH:process.env.PATH,HOME:process.env.HOME,PYTHONPATH:`${path.join(repoRoot,'src')}:${repoRoot}`,SUPABASE_URL:gateway.url,SUPABASE_SERVICE_ROLE_KEY:'local-harness-service-key'},
        });
        return JSON.parse(stdout.split('\n').find(line=>line.startsWith('HARNESS_PLAN=')).slice('HARNESS_PLAN='.length));
      };
      const days=(await db.query('select d.* from program_days d join programs p on p.id=d.program_id where p.coach_id=$1 and p.title=$2 order by day_number',[coach.id,"Tristan's Three-Day Foundation Program"])).rows;
      const day2=await load();
      assert.equal(day2.program_day_id,days[1].id);
      assert.equal(day2.plan,'jumping jacks:20,jumping jacks:20,jumping jacks:20,squats:12,squats:12,squats:12,lunges:10,lunges:10,lunges:10');
      assert.equal(day2.client_name,'Ryan');assert.equal(day2.coach_name,'Tristan');
      await page.getByLabel('Client',{exact:true}).selectOption(client.id);
      await page.getByLabel('Training day',{exact:true}).selectOption(days[0].id);
      await page.getByRole('button',{name:'Assign training day',exact:true}).click();
      await expect(page.getByRole('status').filter({hasText:'Day assigned'})).toBeVisible();
      await expect.poll(async()=> (await db.query('select program_day_id from assignments where client_id=$1 and active',[client.id])).rows).toEqual([{program_day_id:days[0].id}]);
      const day1=await load();
      assert.equal(day1.program_day_id,days[0].id);
      assert.equal(day1.day_number,1);assert.equal(day1.day_title,'Full Body Foundations');
      assert.equal(day1.plan,'squats:10,squats:10,squats:10,pushups:8,pushups:8,pushups:8,lunges:10,lunges:10,bicep curls:12,bicep curls:12,bicep curls:12');
      assert.deepEqual(day1.items,days[0].exercises);
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
