import http from 'node:http';
import { mkdir, writeFile, rm } from 'node:fs/promises';
import path from 'node:path';

/** Narrow HTTP Supabase emulator: transport only; all relational work runs real SQL. */
export async function createGateway(db, directory) {
  await mkdir(directory, {recursive: true});
  const connection = await db.connect({role: "service_role"});
  const objects = new Map();
  const requests = [];
  const identifier = value => { if (!/^[a-z_]+$/.test(value)) throw Error('Unsupported SQL identifier'); return `"${value}"`; };
  const server = http.createServer(async (req, res) => {
    const send = (status, data) => { res.writeHead(status, {'content-type': 'application/json'}); res.end(JSON.stringify(data)); };
    try {
      if (req.headers.apikey !== 'local-harness-service-key') return send(401, {message:'Missing harness key'});
      const url = new URL(req.url, 'http://localhost');
      requests.push({method:req.method, path:url.pathname});
      const chunks = []; for await (const chunk of req) chunks.push(chunk);
      const bytes = Buffer.concat(chunks);
      if (url.pathname.startsWith('/storage/v1/object/programs')) {
        if (req.method === 'POST') {
          const key = decodeURIComponent(url.pathname.slice('/storage/v1/object/programs/'.length));
          if (!/^[a-f0-9-]+\/[a-f0-9-]+\.pdf$/.test(key)) throw Error('Unexpected storage key');
          const file = path.join(directory, key); await mkdir(path.dirname(file), {recursive:true}); await writeFile(file, bytes);
          objects.set(key, bytes); return send(200, {Key:`programs/${key}`});
        }
        if (req.method === 'DELETE') {
          for (const key of JSON.parse(bytes).prefixes) { if (objects.has(key)) { await rm(path.join(directory,key)); objects.delete(key); } }
          return send(200, []);
        }
      }
      if (url.pathname.startsWith('/rest/v1/rpc/') && req.method === 'POST') {
        const fn = url.pathname.split('/').at(-1);
        const params = JSON.parse(bytes);
        const signatures = {save_coach_program:['p_token','p_pdf_path','p_program'],assign_coach_program_day:['p_token','p_client_id','p_day_id']};
        if (!signatures[fn]) throw Error('Unsupported RPC');
        const names = signatures[fn];
        const result = await connection.query(`select ${identifier(fn)}(${names.map((n,i)=>`${identifier(n)} => $${i+1}`).join(',')}) as result`, names.map(n=>typeof params[n] === 'object' ? JSON.stringify(params[n]) : params[n]));
        return send(200,result.rows[0].result);
      }
      const table = url.pathname.split('/').at(-1);
      if (!url.pathname.startsWith('/rest/v1/') || req.method !== 'GET' || !['coaches','clients','programs','program_days','assignments'].includes(table)) throw Error('Unsupported gateway request');
      // Exact PostgREST relationship projection used by the real Python worker.
      const workerProjection = 'program_day_id,clients(name),program_days(id,day_number,title,exercises,programs(coach_id,coaches(name,persona)))';
      if (table === 'assignments' && url.searchParams.get('select') === workerProjection) {
        if (url.searchParams.get('active') !== 'eq.true' || url.searchParams.get('order') !== 'assigned_at.desc' || url.searchParams.get('limit') !== '1') throw Error('Unsupported worker assignment query');
        const clientFilter = url.searchParams.get('client_id') || '';
        if (!clientFilter.startsWith('eq.')) throw Error('Missing worker client filter');
        const result = await connection.query(`
          select a.program_day_id, json_build_object('name', c.name) as clients,
            json_build_object('id', d.id, 'day_number', d.day_number, 'title', d.title, 'exercises', d.exercises,
              'programs', json_build_object('coach_id', p.coach_id,
                'coaches', json_build_object('name', co.name, 'persona', co.persona))) as program_days
          from assignments a join clients c on c.id=a.client_id
          join program_days d on d.id=a.program_day_id join programs p on p.id=d.program_id
          join coaches co on co.id=p.coach_id
          where a.client_id=$1 and a.active=true order by a.assigned_at desc limit 1`, [clientFilter.slice(3)]);
        return send(200,result.rows);
      }
      const columns = (url.searchParams.get('select') || '*').split(',').map(identifier).join(',');
      const values = [], filters = [];
      for (const [key, value] of url.searchParams) {
        if (['select','order'].includes(key)) continue;
        if (value.startsWith('eq.')) {values.push(value.slice(3));filters.push(`${identifier(key)} = $${values.length}`);}
        else if (value.startsWith('in.(') && value.endsWith(')')) { const items=value.slice(4,-1).split(','); const slots=items.map(x=>{values.push(x);return `$${values.length}`;});filters.push(`${identifier(key)} in (${slots})`); }
        else throw Error('Unsupported filter');
      }
      const ordering = url.searchParams.get('order');
      let order = '';
      if (ordering) { const [col, direction] = ordering.split('.'); if (!['asc','desc'].includes(direction)) throw Error('Bad ordering'); order=` order by ${identifier(col)} ${direction}`; }
      const result = await connection.query(`select ${columns} from ${identifier(table)}${filters.length?' where '+filters.join(' and '):''}${order}`, values);
      return send(200, req.headers.accept?.includes('vnd.pgrst.object') ? result.rows[0] ?? null : result.rows);
    } catch (error) { send(400, {code:error.code || 'HARNESS',message:error.message}); }
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  return {url:`http://127.0.0.1:${server.address().port}`,objects,requests,stop:async()=>{await new Promise(resolve=>server.close(resolve));await connection.end();}};
}
