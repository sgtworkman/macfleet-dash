// Keep a burst of optional sources within small loopback servers' connection
// queues. Preserve source order and independent failures, never fake a result.
export async function readSources(urls,read,limit=3){
  if(!Number.isInteger(limit)||limit<1||limit>6)throw new RangeError('Invalid snapshot read concurrency');
  const results=[];
  for(let start=0;start<urls.length;start+=limit){
    results.push(...await Promise.allSettled(urls.slice(start,start+limit).map(url=>Promise.resolve().then(()=>read(url)))));
  }
  return results;
}
