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
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function stopChild(child) {
  if(!child.pid || child.exitCode!==null || child.signalCode!==null)return;
  const exited=new Promise(resolve=>child.once('exit',resolve));
  try{process.kill(-child.pid,'SIGTERM');}catch(error){if(error.code!=='ESRCH')throw error;}
  if(await Promise.race([exited.then(()=>true),delay(3000).then(()=>false)]))return;
  try{process.kill(-child.pid,'SIGKILL');}catch(error){if(error.code!=='ESRCH')throw error;}
  if(!await Promise.race([exited.then(()=>true),delay(3000).then(()=>false)]))throw Error('Child process did not exit after SIGKILL');
}
async function command(label,executable,args,options={}) {
  const log=createWriteStream(path.join(artifacts,`${label}.log`));
  const child=spawn(executable,args,{cwd:repoRoot,env:cleanEnv,...options,stdio:['ignore','pipe','pipe'],detached:true});
  child.stdout.pipe(log);child.stderr.pipe(log);
  let timer;
  try {
    const exit=new Promise((resolve,reject)=>{child.on('error',reject);child.on('exit',resolve);});
    const timeout=new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error(`${label} exceeded 120s deadline`)),120000);});
    const code=await Promise.race([exit,timeout]);
    if(code!==0)throw Error(`${label} exited ${code}; see .local/harness/${label}.log`);
    report.tests.push({name:label,status:'passed'});
  } finally {clearTimeout(timer);await stopChild(child);log.end();}
}
let db,gateway,server,temp;
try {
  await command('database',process.execPath,['--test',path.join(here,'database.test.mjs')]);
  const python=process.env.HARNESS_PYTHON || path.join(repoRoot,'.venv/bin/python');
  await command('replay',python,[path.join(here,'replay.py'),'--output',path.join(artifacts,'replay')]);
  db=await createDatabaseHarness({repoRoot});
  gateway=await createGateway(db,path.join(artifacts,'storage'));
  temp=await mkdtemp(path.join(os.tmpdir(),'brodie-web-harness-'));
  // Never copy .env files or reuse a developer server: own clean app, build and process.
  await cp(path.join(repoRoot,'web'),temp,{recursive:true,filter:source=>!['node_modules','.next','.git'].includes(path.basename(source))&&!path.basename(source).startsWith('.env')});
  await symlink(path.join(repoRoot,'web/node_modules'),path.join(temp,'node_modules'),'dir');
  const modeFile=path.join(artifacts,'gemini-mode');const callsFile=path.join(artifacts,'gemini-calls.jsonl');
  await writeFile(modeFile,'success');await writeFile(callsFile,'');
  const env={...cleanEnv,SUPABASE_URL:gateway.url,SUPABASE_SERVICE_ROLE_KEY:'local-harness-service-key',GEMINI_PARSER_API_KEY:'local-harness-parser-key',NODE_OPTIONS:`--require=${path.join(here,'gemini-preload.cjs')}`,HARNESS_PDF:path.join(repoRoot,'db/fixtures/sample_program.pdf'),HARNESS_PROGRAM:path.join(repoRoot,'db/fixtures/sample_program.expected.json'),HARNESS_GEMINI_MODE:modeFile,HARNESS_GEMINI_CALLS:callsFile};
  // Development webpack server avoids an external Google Fonts build dependency.
  const reservation=net.createServer();await new Promise(r=>reservation.listen(0,'127.0.0.1',r));const port=reservation.address().port;await new Promise(r=>reservation.close(r));
  const log=createWriteStream(path.join(artifacts,'next.log'));
  server=spawn(process.execPath,[path.join(repoRoot,'web/node_modules/next/dist/bin/next'),'dev','--webpack','--hostname','127.0.0.1','--port',String(port)],{cwd:temp,env,stdio:['ignore','pipe','pipe'],detached:true});server.stdout.pipe(log);server.stderr.pipe(log);
  const url=`http://127.0.0.1:${port}`;
  let ready=false;for(let i=0;i<120;i++){if(server.exitCode!==null)throw Error('Next server exited; see next.log');try{await fetch(`${url}/favicon.ico`,{signal:AbortSignal.timeout(1000)});ready=true;break;}catch{await new Promise(r=>setTimeout(r,500));}}
  if(!ready)throw Error('Next server readiness timed out');
  await runBrowserTests({db,gateway,url,repoRoot,artifacts,modeFile,callsFile,results:report.tests});
  report.status='passed';
} catch(error) {report.status='failed';report.error=error.stack;process.exitCode=1;console.error(error.stack);}
finally {
  const cleanupErrors=[];
  let serverStopped=true;
  if(server){try{await stopChild(server);}catch(error){serverStopped=false;cleanupErrors.push(error.message);}}
  for(const cleanup of [()=>gateway?.stop(),()=>db?.stop(),()=>temp&&serverStopped?rm(temp,{recursive:true,force:true}):undefined]) {
    try{await cleanup();}catch(error){cleanupErrors.push(error.message);}
  }
  if(cleanupErrors.length){report.status='failed';report.cleanup_errors=cleanupErrors;}
  report.finished_at=new Date().toISOString();await writeFile(path.join(artifacts,'report.json'),JSON.stringify(report,null,2)+'\n');
  console.log(`${report.status.toUpperCase()}: ${report.tests.length} checks; ${path.join(artifacts,'report.json')}`);
  // Explicit exit preserves failure status against child-process library exit hooks.
  process.exit(report.status==='passed'?0:1);
}
