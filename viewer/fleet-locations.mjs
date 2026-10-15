// Location labels only. Never change telemetry, identities or enrollment.
export const LOCATION_STORAGE_KEY = 'macfleet-locations-v1';
const hostId = /^[a-z0-9][a-z0-9.-]{0,62}$/;
export function locationName(value) {
  if (typeof value !== 'string') throw Error('Location must be text.');
  const label = value.trim() || 'Unassigned';
  if ([...label].length > 80 || /[\u0000-\u001f\u007f-\u009f\u202a-\u202e\u2066-\u2069]/.test(label)) throw Error('Use a location of at most 80 characters without control characters.');
  if (label === 'all') throw Error('The name “all” is reserved for the location filter.');
  return label;
}
export function checkedLocations(value) {
  if (value?.schema !== 'macfleet.locations.v1' || !value.locations || typeof value.locations !== 'object' || Array.isArray(value.locations) || Object.keys(value).some(k => !['schema','locations'].includes(k))) throw Error('Location settings format is invalid.');
  const entries = Object.entries(value.locations);
  if (entries.length > 512 || entries.some(([key]) => !hostId.test(key))) throw Error('Location computer IDs are invalid.');
  return Object.fromEntries(entries.map(([key, label]) => [key, locationName(label)]));
}
export const locationsDocument = locations => ({schema:'macfleet.locations.v1',locations:checkedLocations({schema:'macfleet.locations.v1',locations})});
export function applyLocations(data, locations) {
  const labels = locationsDocument(locations).locations;
  return data ? {...data,hosts:data.hosts.map(row => Object.hasOwn(labels,row.host) ? {...row,site:labels[row.host]} : row)} : data;
}
export function editedLocations(baseHosts, saved, edits) {
  const result = {...locationsDocument(saved).locations};
  const base = new Map(baseHosts.map(row => [row.host,locationName(row.site || '')]));
  for (const [key,label] of Object.entries(locationsDocument(edits).locations)) {
    if (!base.has(key)) throw Error('A computer changed while editing. Refresh before saving.');
    if (label === base.get(key)) delete result[key]; else result[key] = label;
  }
  return locationsDocument(result).locations;
}
export function exportLocations(hosts, edits = {}) {
  const draft = locationsDocument(edits).locations;
  return locationsDocument(Object.fromEntries(hosts.map(row => [row.host,Object.hasOwn(draft,row.host) ? draft[row.host] : locationName(row.site || '')])));
}
