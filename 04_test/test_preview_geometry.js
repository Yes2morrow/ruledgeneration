const assert = require('node:assert/strict');
const test = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../webui/static/app.js'), 'utf8');
function load(extra = {}) {
    const context = vm.createContext({ ...extra });
    const names = ['normalizeRotation', 'groupGridGeometry', 'normalizeArrangement', 'isObject',
        'transformDirection', 'transformModulePointToWorld', 'drawModuleCell'];
    for (const name of names) {
        const start = source.indexOf(`function ${name}(`);
        if (start < 0) continue;
        const end = source.indexOf('\n}', start) + 2;
        vm.runInContext(source.slice(start, end), context);
    }
    return context;
}
test('preview points and directions use clockwise quarter turns with positive footprints', () => {
    const c = load();
    const points = [[500, 250], [250, 3500], [3500, 1750], [1750, 500]];
    for (let k = 0; k < 4; k++) {
        const p = c.transformModulePointToWorld(500, 250, 4000, 2000, 10, 20, k * 90, 'none');
        assert.deepEqual(Array.from(p), [points[k][0] + 10, points[k][1] + 20]);
        assert.equal(c.transformDirection('north', k * 90, 'none'), ['north', 'east', 'south', 'west'][k]);
    }
    assert.deepEqual(Array.from(c.transformModulePointToWorld(500, 250, 4000, 2000, 0, 0, 90, 'both')), [1750, 500]);
});
test('mixed rotated cells determine grid footprint and cell offsets', () => {
    const c = load();
    const grid = c.groupGridGeometry({ rows: 2, cols: 2,
        internal_spacing: { horizontal_gap_m: 0.5, vertical_gap_m: 1 },
        arrangement: [{ row: 0, col: 0, rotation: 90 }, { row: 0, col: 1, rotation: 0 },
            { row: 1, col: 0, rotation: 270 }, { row: 1, col: 1, rotation: 180 }] }, { L: 4000, W: 2000 });
    assert.equal(grid.gw, 6500);
    assert.equal(grid.gh, 9000);
    assert.deepEqual(Array.from(grid.xs), [0, 2500]);
    assert.deepEqual(Array.from(grid.ys), [0, 5000]);
});
test('canvas texture uses the same rotation and occupied center as bed geometry', () => {
    let center, rotation;
    const ctx = new Proxy({}, { get: (_, key) => (...args) => {
        if (key === 'translate') center = args;
        if (key === 'rotate') rotation = args[0];
    }, set: () => true });
    const c = load({ ctx, MIRROR_COLORS: { none: '#ffffff' }, state: { data: { module_id: 'B' } },
        view: { scale: 1 }, w2s: (x, y) => [x, -y], getModuleDims: () => ({ data: null }),
        loadTexture: () => null, hexToRgba: () => '#ffffff' });
    c.drawModuleCell(10, 20, 4000, 2000, { row: 0, col: 0, rotation: 90 }, {});
    assert.deepEqual(center, [1010, -2020]);
    assert.equal(rotation, Math.PI / 2);
});
