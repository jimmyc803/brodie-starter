import { readFile } from 'node:fs/promises';
// @ts-expect-error Node's native TypeScript runner requires the .ts extension.
import { parseProgram, ProgramParseError } from '../lib/parseProgram.ts';

const filename = process.argv[2];
if (!filename) {
  console.error('Usage: npm run parse:program -- path/to/program.pdf');
  process.exitCode = 1;
} else {
  try {
    const result = await parseProgram(await readFile(filename));
    console.log(JSON.stringify(result, null, 2));
  } catch (error) {
    console.error(error instanceof ProgramParseError ? `${error.code}: ${error.message}` : 'Could not read the PDF file. Check its path and permissions.');
    process.exitCode = 1;
  }
}
