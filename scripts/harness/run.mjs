import { createLifecycle, stopChild } from './lifecycle.mjs';
import { createDatabaseHarness } from './database.mjs';
import { createGateway } from './gateway.mjs';
import { runBrowserTests } from './browser.mjs';
import { spawn } from 'node:child_process';
import { mkdir, writeFile, mkdtemp, cp, symlink, rm } from 'node:fs/promises';
import { createWriteStream } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import os from 'node:os';
import net from 'node:net';
const here=path.dirname(fileURLToPath(import.meta.url));
const repoRoot=path.resolve(here,'../..');
const artifacts=path.join(repoRoot,'.local/harness');
await mkdir(artifacts,{recursive:true});
const report={started_at:new Date().toISOString(),status:'running',boundaries:{database:'real PostgreSQL, repository schema and migration',web:'real Next.js, React forms, server actions and parser',gemini:'deterministic external HTTP response double; no real AI validation',storage:'local HTTP adapter with real temporary PDF files; not Supabase hosted storage',video:'synthetic 10-fps landmarks; not camera/device validation'},tests:[]};
const cleanEnv={PATH:process.env.PATH,HOME:process.env.HOME,TMPDIR:process.env.TMPDIR,LANG:'en_US.UTF-8',CI:'1',NEXT_TELEMETRY_DISABLED:'1'};
const lifecycle=await createLifecycle(path.join(artifacts,'report.json'),report);
async function command(label,executable,args,options={}) {
  lifecycle.check();
  const log=createWriteStream(path.join(artifacts,`${label}.log`));
  const child=spawn(executable,args,{cwd:repoRoot,env:cleanEnv,...options,stdio:['ignore','pipe','pipe'],detached:true});
  const untrack=lifecycle.track(()=>stopChild(child));
  child.stdout.pipe(log);child.stderr.pipe(log);
  let timer;
  try {
    const exit=new Promise((resolve,reject)=>{child.on('error',reject);child.on('exit',resolve);});
    const timeout=new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error(`${label} exceeded 120s deadline`)),120000);});
    const code=await Promise.race([exit,timeout]);
    if(code!==0)throw Error(`${label} exited ${code}; see .local/harness/${label}.log`);
    report.tests.push({name:label,status:'passed'});
  } finally {clearTimeout(timer);await stopChild(child);untrack();log.end();}
}
let db,gateway,server,temp;
try {
  await command('lifecycle',process.execPath,['--test',path.join(here,'lifecycle.test.mjs')]);
  await command('sync-contract',process.execPath,[path.join(repoRoot,'web/scripts/sync-contract.mjs')]);
  await command('database',process.execPath,['--test',path.join(here,'database.test.mjs')]);
  const python=process.env.HARNESS_PYTHON || path.join(repoRoot,'.venv/bin/python');
  await command('replay',python,[path.join(here,'replay.py'),'--output',path.join(artifacts,'replay')]);
  db=await lifecycle.acquire(()=>createDatabaseHarness({repoRoot}),value=>value.stop());
  gateway=await lifecycle.acquire(()=>createGateway(db,path.join(artifacts,'storage')),value=>value.stop());
  temp=await lifecycle.acquire(()=>mkdtemp(path.join(os.tmpdir(),'brodie-web-harness-')),value=>rm(value,{recursive:true,force:true}));
  // Never copy .env files or reuse a developer server: own clean app, build and process.
  await lifecycle.acquire(()=>cp(path.join(repoRoot,'web'),temp,{recursive:true,filter:source=>!['node_modules','.next','.git'].includes(path.basename(source))&&!path.basename(source).startsWith('.env')}),()=>{});
  lifecycle.check();
  await symlink(path.join(repoRoot,'web/node_modules'),path.join(temp,'node_modules'),'dir');
  const modeFile=path.join(artifacts,'gemini-mode');const callsFile=path.join(artifacts,'gemini-calls.jsonl');
  await writeFile(modeFile,'success');await writeFile(callsFile,'');
  const env={...cleanEnv,SUPABASE_URL:gateway.url,SUPABASE_SERVICE_ROLE_KEY:'local-harness-service-key',GEMINI_PARSER_API_KEY:'local-harness-parser-key',NODE_OPTIONS:`--require=${path.join(here,'gemini-preload.cjs')}`,HARNESS_PDF:path.join(repoRoot,'db/fixtures/sample_program.pdf'),HARNESS_PROGRAM:path.join(repoRoot,'db/fixtures/sample_program.expected.json'),HARNESS_GEMINI_MODE:modeFile,HARNESS_GEMINI_CALLS:callsFile};
  // Development webpack server avoids an external Google Fonts build dependency.
  const reservation=net.createServer();await new Promise(r=>reservation.listen(0,'127.0.0.1',r));const port=reservation.address().port;await new Promise(r=>reservation.close(r));
  lifecycle.check();
  const log=createWriteStream(path.join(artifacts,'next.log'));
  server=spawn(process.execPath,[path.join(repoRoot,'web/node_modules/next/dist/bin/next'),'dev','--webpack','--hostname','127.0.0.1','--port',String(port)],{cwd:temp,env,stdio:['ignore','pipe','pipe'],detached:true});lifecycle.track(async()=>{await stopChild(server);log.end();});server.stdout.pipe(log);server.stderr.pipe(log);
  const url=`http://127.0.0.1:${port}`;
  let ready=false;for(let i=0;i<120;i++){lifecycle.check();if(server.exitCode!==null)throw Error('Next server exited; see next.log');try{await fetch(`${url}/favicon.ico`,{signal:AbortSignal.timeout(1000)});ready=true;break;}catch{await new Promise(r=>setTimeout(r,500));}}
  if(!ready)throw Error('Next server readiness timed out');
  await runBrowserTests({db,gateway,url,repoRoot,artifacts,modeFile,callsFile,results:report.tests,acquireBrowser:promise=>lifecycle.acquire(promise,browser=>browser.close())});
  lifecycle.check();
  report.status='passed';
} catch(error) {report.status='failed';report.error=error.stack;process.exitCode=1;console.error(error.stack);}
finally {
  await lifecycle.exit();
}
