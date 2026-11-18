import {triggerDueScan} from '../lib/github-scan-trigger.mjs';
const decision=await triggerDueScan({repository:process.env.GITHUB_REPOSITORY,token:process.env.GH_TOKEN});
console.log(JSON.stringify(decision));
