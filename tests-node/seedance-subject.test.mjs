import test from 'node:test';
import assert from 'node:assert/strict';
import { validateSeedanceSubject } from '../scripts/video_gateway.mjs';

test('Seedance 2 rejects unclassified portraits and directs real faces to qualified native adapter', () => {
  for (const model of ['doubao-seedance-2-0-260128', 'doubao-seedance-2-5-260628']) {
    assert.throws(() => validateSeedanceSubject(model, {}), /确认素材/);
    assert.throws(() => validateSeedanceSubject(model, { subject: { type: 'real-person' } }), /asset:\/\//);
    assert.doesNotThrow(() => validateSeedanceSubject(model, { subject: { type: 'fictional' } }));
  }
  assert.doesNotThrow(() => validateSeedanceSubject('grok-imagine-video', {}));
});
