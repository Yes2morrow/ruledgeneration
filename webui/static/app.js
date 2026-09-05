/* ==========================================================================
   规则系统2.0 配置编辑器 - 前端逻辑
   功能: 文件列表 / YAML 文本编辑 / Canvas 可视化预览 / 属性表单双向绑定 / 保存
   纯 JS 实现, 不依赖任何外部库; YAML 解析与序列化通过后端 /api/yaml/* 完成
   ========================================================================== */
'use strict';

/* ----------------------- 全局状态 ----------------------- */
const state = {
    cat: 'modules',          // 当前类别: modules | groups
    filename: null,          // 当前打开的文件名
    data: null,              // 结构化数据(编辑的真相来源)
    text: '',                // YAML 文本(编辑器内容)
    dirty: false,            // 是否有未保存改动
    listCache: {},           // 各类别的文件列表缓存
    moduleCache: {},         // 模块配置缓存(module_id -> data), 用于群组预览
    history: [],             // 撤销历史栈(深拷贝快照)
    historyIndex: -1,        // 当前历史位置
    historyMax: 50,          // 最大历史记录数
};

/* 镜像方式 -> 颜色 */
const MIRROR_COLORS = {
    none:       '#4fc3f7',  // 蓝
    vertical:   '#66bb6a',  // 绿(上下镜像)
    horizontal: '#ffa726',  // 橙(左右镜像)
    both:       '#ef5350',  // 红(双向镜像)
};

/* 纹理缓存: url -> Image */
const textureCache = {};

function getTextureUrl(filename) {
    if (!filename) return null;
    return `/textures/${filename}`;
}

function loadTexture(filename) {
    const url = getTextureUrl(filename);
    if (!url) return null;
    if (textureCache[url]) return textureCache[url];
    const img = new Image();
    img.onload = () => { if (state.data) draw(); };
    img.onerror = () => { textureCache[url] = { failed: true }; if (state.data) draw(); };
    img.src = url;
    textureCache[url] = img;
    return img;
}

/* ----------------------- DOM 引用 ----------------------- */
const $ = (sel) => document.querySelector(sel);
const els = {
    fileList: $('#file-list'),
    search: $('#search-input'),
    tabs: document.querySelectorAll('.tab'),
    fileLabel: $('#current-file-label'),
    status: $('#status-msg'),
    btnUndo: $('#btn-undo'),
    btnRedo: $('#btn-redo'),
    btnApply: $('#btn-apply-yaml'),
    btnSave: $('#btn-save'),
    btnFit: $('#btn-fit'),
    btnZoomIn: $('#btn-zoom-in'),
    btnZoomOut: $('#btn-zoom-out'),
    btnReset: $('#btn-reset'),
    zoomLabel: $('#zoom-label'),
    canvas: $('#preview-canvas'),
    canvasEmpty: $('#canvas-empty'),
    parseBanner: $('#parse-error-banner'),
    legend: $('#legend'),
    yaml: $('#yaml-editor'),
    propsBody: $('#props-body'),
    resizer: $('#resizer-v'),
    center: $('.center'),
    yamlPane: $('.yaml-pane'),
};

const ctx = els.canvas.getContext('2d');

/* ----------------------- 通用工具 ----------------------- */
function setStatus(msg, kind) {
    els.status.textContent = msg || '';
    els.status.className = 'status-msg' + (kind ? ' ' + kind : '');
}

function flash(msg, kind) {
    setStatus(msg, kind);
    if (kind === 'ok') setTimeout(() => { if (els.status.textContent === msg) setStatus(''); }, 2500);
}

function isObject(v) { return v !== null && typeof v === 'object' && !Array.isArray(v); }
function isArray(v) { return Array.isArray(v); }
function isNumberArray(v) { return isArray(v) && v.length > 0 && v.every(x => typeof x === 'number'); }
function isNumberMatrix(v) { return isArray(v) && v.length > 0 && v.every(x => isNumberArray(x)); }

/* 按路径读写结构化数据 */
function getByPath(obj, path) {
    let cur = obj;
    for (const p of path) { if (cur == null) return undefined; cur = cur[p]; }
    return cur;
}
function setByPath(obj, path, value) {
    let cur = obj;
    for (let i = 0; i < path.length - 1; i++) {
        if (cur[path[i]] == null) cur[path[i]] = (typeof path[i + 1] === 'number') ? [] : {};
        cur = cur[path[i]];
    }
    cur[path[path.length - 1]] = value;
}
function deleteByPath(obj, path) {
    const parent = getByPath(obj, path.slice(0, -1));
    const last = path[path.length - 1];
    if (parent == null) return;
    if (isArray(parent)) parent.splice(Number(last), 1);
    else delete parent[last];
}

/* 输入框文本 -> 标量(尽量保留数值类型) */
function parseScalar(raw) {
    const s = String(raw).trim();
    if (s === '') return '';
    if (/^-?\d+$/.test(s)) return parseInt(s, 10);
    if (/^-?\d+\.\d+$/.test(s)) return parseFloat(s);
    if (s === 'true') return true;
    if (s === 'false') return false;
    if (s === 'null' || s === '~') return null;
    return raw;
}

/* ===================== API 封装 ===================== */
async function apiGet(url) {
    const r = await fetch(url);
    if (!r.ok) {
        const t = await r.text();
        throw new Error(`${r.status}: ${t}`);
    }
    return r.json();
}
async function apiPost(url, body) {
    const r = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    });
    if (!r.ok) {
        const t = await r.text();
        throw new Error(`${r.status}: ${t}`);
    }
    return r.json();
}
async function apiPut(url, body) {
    const r = await fetch(url, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    });
    if (!r.ok) {
        const t = await r.text();
        throw new Error(`${r.status}: ${t}`);
    }
    return r.json();
}

/* ===================== 文件列表 ===================== */
async function loadList(cat) {
    state.cat = cat;
    els.tabs.forEach(t => t.classList.toggle('active', t.dataset.cat === cat));
    if (!state.listCache[cat]) {
        try {
            state.listCache[cat] = await apiGet(`/api/configs/${cat}`);
        } catch (e) {
            state.listCache[cat] = [];
            flash('加载列表失败: ' + e.message, 'err');
        }
    }
    renderList();
}

function renderList() {
    const items = state.listCache[state.cat] || [];
    const kw = els.search.value.trim().toLowerCase();
    els.fileList.innerHTML = '';
    if (items.length === 0) {
        els.fileList.innerHTML = '<li class="props-empty">无文件</li>';
        return;
    }
    items.forEach(it => {
        const name = it.filename || '';
        if (kw && !name.toLowerCase().includes(kw) && !(it.name || '').toLowerCase().includes(kw)) return;
        const li = document.createElement('li');
        li.className = 'file-item' + (it.filename === state.filename ? ' active' : '');
        let meta = '';
        if (state.cat === 'modules') meta = `${it.name || ''} · ${it.type || ''}`;
        else if (state.cat === 'groups') meta = `模块 ${it.module_id || ''} · ${(it.group_types || []).join(', ')}`;
        li.innerHTML = `<span class="fname">${name}</span>` +
            (meta ? `<span class="fmeta">${meta}</span>` : '') +
            (it.parse_error ? `<span class="ferr">⚠ 解析错误</span>` : '');
        li.addEventListener('click', () => openFile(it.filename));
        els.fileList.appendChild(li);
    });
}

/* ===================== 打开文件 ===================== */
async function openFile(filename) {
    state.filename = filename;
    els.fileLabel.textContent = filename;
    renderList();  // 更新左侧文件列表高亮
    flash('加载中…');
    try {
        const res = await apiGet(`/api/configs/${state.cat}/${encodeURIComponent(filename)}`);
        state.text = res.text || '';
        state.data = res.data || null;
        els.yaml.value = state.text;
        els.btnSave.disabled = true;
        state.dirty = false;

        // 错误/修复提示
        if (res.error) {
            showBanner(res.error, true);
            els.canvasEmpty.classList.remove('hidden');
            els.canvasEmpty.textContent = '解析失败, 无法生成预览';
            els.legend.classList.add('hidden');
            clearCanvas();
            renderProps(null);
            setStatus('解析错误', 'err');
            return;
        }
        if (res.repaired) {
            showBanner('该文件含非标准 YAML 语法(arrangement 单行写法), 已自动修复以便预览与编辑。保存后将规范化为合法 YAML。', false);
        } else {
            hideBanner();
        }

        renderProps(state.data);
        resetViewAndDraw();

        // 打开文件时重置历史, 初始状态作为第一个快照
        state.history = [deepClone(state.data)];
        state.historyIndex = 0;
        updateUndoRedoButtons();

        setStatus('已加载', 'ok');
        setTimeout(() => setStatus(''), 1500);
    } catch (e) {
        flash('打开失败: ' + e.message, 'err');
    }
}

function showBanner(msg, isError) {
    els.parseBanner.textContent = msg;
    els.parseBanner.classList.remove('hidden', 'err');
    if (isError) els.parseBanner.classList.add('err');
}
function hideBanner() { els.parseBanner.classList.add('hidden'); }

/* ===================== YAML 文本 <-> 数据 同步 ===================== */
let syncTimer = null;
let suppressSync = false;  // 防止程序化更新触发循环

/* 表单改动后, 把结构化数据序列化回编辑器(防抖) */
function scheduleSyncText() {
    if (suppressSync) return;
    clearTimeout(syncTimer);
    syncTimer = setTimeout(async () => {
        if (!state.data) return;
        try {
            const res = await apiPost('/api/yaml/dump', { data: state.data });
            suppressSync = true;
            state.text = res.text;
            els.yaml.value = res.text;
        } catch (e) { /* 忽略 */ } finally {
            suppressSync = false;
        }
    }, 300);
}

/* "应用YAML"按钮: 把编辑器文本解析为结构化数据 */
async function applyYaml() {
    const text = els.yaml.value;
    try {
        const res = await apiPost('/api/yaml/parse', { text });
        if (res.error) {
            showBanner(res.error, true);
            flash('YAML 解析失败', 'err');
            return;
        }
        state.data = res.data;
        state.text = text;
        if (res.repaired) {
            showBanner('文本含非标准 arrangement 写法, 已自动修复并加载。', false);
        } else {
            hideBanner();
        }
        pushHistory();          // YAML 应用前记录快照
        renderProps(state.data);
        resetViewAndDraw();
        markDirty();
        flash('已应用 YAML', 'ok');
    } catch (e) {
        flash('应用失败: ' + e.message, 'err');
    }
}

function markDirty() {
    state.dirty = true;
    els.btnSave.disabled = false;
    els.fileLabel.textContent = (state.filename || '') + ' ●';
}

/* ===================== 保存 ===================== */
async function save() {
    if (!state.filename || !state.data) return;
    flash('保存中…');
    try {
        await apiPut(`/api/configs/${state.cat}/${encodeURIComponent(state.filename)}`, { data: state.data });
        state.dirty = false;
        els.btnSave.disabled = true;
        els.fileLabel.textContent = state.filename;
        // 刷新列表缓存(可能 name/type 变化)
        delete state.listCache[state.cat];
        loadList(state.cat);
        flash('保存成功', 'ok');
    } catch (e) {
        flash('保存失败: ' + e.message, 'err');
    }
}

/* ===================== 属性表单(递归, 双向绑定) ===================== */
function renderProps(data) {
    els.propsBody.innerHTML = '';
    if (!isObject(data)) {
        els.propsBody.innerHTML = '<div class="props-empty">暂无可编辑属性</div>';
        return;
    }
    const root = document.createElement('div');
    root.className = 'field';
    renderObject(data, [], root, true);
    els.propsBody.appendChild(root);
}

/* 渲染对象: container 已创建 */
function renderObject(obj, path, container, isRoot) {
    Object.keys(obj).forEach(key => {
        const childPath = path.concat(key);
        const val = obj[key];
        const node = renderNode(val, key, childPath);
        container.appendChild(node);
    });
}

/* 渲染任意节点, 返回 DOM 元素 */
function renderNode(value, key, path) {
    const wrap = document.createElement('div');
    wrap.className = 'field';

    // arrangement: 数组且元素为含 row/col/rotation/mirror 的对象 -> 紧凑行
    if (isArray(value) && value.length > 0 && value.every(v => isObject(v) && 'row' in v && 'col' in v && 'mirror' in v)) {
        wrap.appendChild(makeSectionHeader(key, path, value, true));
        const child = document.createElement('div');
        child.className = 'field-children';
        value.forEach((item, i) => {
            child.appendChild(renderArrangementRow(item, path.concat(i), i));
        });
        child.appendChild(makeAddButton(path, () => {
            const arr = getByPath(state.data, path);
            arr.push({ row: 0, col: 0, rotation: 0, mirror: 'none' });
            afterStructChange();
        }));
        wrap.appendChild(child);
        return wrap;
    }

    // 数字矩阵(如 polygon, points): 数组且元素均为数字数组 -> 紧凑坐标行
    if (isNumberMatrix(value)) {
        wrap.appendChild(makeSectionHeader(key, path, value, true));
        const child = document.createElement('div');
        child.className = 'field-children';
        value.forEach((pt, i) => {
            child.appendChild(renderTupleRow(pt, path.concat(i), i));
        });
        child.appendChild(makeAddButton(path, () => {
            const arr = getByPath(state.data, path);
            const len = arr.length && isArray(arr[0]) ? arr[0].length : 2;
            arr.push(new Array(len).fill(0));
            afterStructChange();
        }));
        wrap.appendChild(child);
        return wrap;
    }

    // road_areas: 数组且元素为含 name/description/polygon 的对象 -> 紧凑道路编辑器
    if (key === 'road_areas' && isArray(value) && value.every(v => isObject(v) && 'polygon' in v)) {
        wrap.appendChild(makeSectionHeader(key, path, value, true));
        const child = document.createElement('div');
        child.className = 'field-children';
        value.forEach((item, i) => {
            child.appendChild(renderRoadRow(item, path.concat(i), i));
        });
        child.appendChild(makeAddButton(path, () => {
            const arr = getByPath(state.data, path);
            arr.push({ name: `aisle_${arr.length + 1}`, description: '', polygon: [[0, 0], [1000, 0], [1000, 1000], [0, 1000]] });
            afterStructChange();
        }));
        wrap.appendChild(child);
        return wrap;
    }

    // beds_layout: 数组且元素为含 bed_id / head_direction / head_position_mm / polygon 的对象 -> 紧凑行
    if (isArray(value) && value.length > 0 && value.every(v => isObject(v) && 'bed_id' in v && 'polygon' in v)) {
        wrap.appendChild(makeSectionHeader(key, path, value, true));
        const child = document.createElement('div');
        child.className = 'field-children';
        value.forEach((item, i) => {
            child.appendChild(renderBedRow(item, path.concat(i), i));
        });
        child.appendChild(makeAddButton(path, () => {
            const arr = getByPath(state.data, path);
            arr.push({ bed_id: arr.length + 1, head_direction: 'north', head_position_mm: 0, polygon: [[0, 0], [1000, 0], [1000, 1000], [0, 1000]] });
            afterStructChange();
        }));
        wrap.appendChild(child);
        return wrap;
    }

    // 普通数组
    if (isArray(value)) {
        wrap.appendChild(makeSectionHeader(key, path, value, true));
        const child = document.createElement('div');
        child.className = 'field-children';
        value.forEach((item, i) => {
            const idxLabel = `[${i}]`;
            if (isObject(item)) {
                const sub = document.createElement('div');
                sub.className = 'field';
                sub.appendChild(makeSectionHeader(idxLabel, path.concat(i), item, false));
                const subChild = document.createElement('div');
                subChild.className = 'field-children';
                renderObject(item, path.concat(i), subChild, false);
                sub.appendChild(subChild);
                child.appendChild(sub);
            } else if (isNumberArray(item)) {
                child.appendChild(renderTupleRow(item, path.concat(i), i));
            } else {
                child.appendChild(renderScalarRow(item, idxLabel, path.concat(i)));
            }
        });
        child.appendChild(makeAddButton(path, () => {
            const arr = getByPath(state.data, path);
            if (arr.length && isObject(arr[arr.length - 1])) arr.push({});
            else if (arr.length && typeof arr[arr.length - 1] === 'number') arr.push(0);
            else arr.push('');
            afterStructChange();
        }));
        wrap.appendChild(child);
        return wrap;
    }

    // 对象
    if (isObject(value)) {
        wrap.appendChild(makeSectionHeader(key, path, value, false));
        const child = document.createElement('div');
        child.className = 'field-children';
        renderObject(value, path, child, false);
        wrap.appendChild(child);
        return wrap;
    }

    // 标量
    wrap.appendChild(renderScalarRow(value, key, path));
    return wrap;
}

/* 可折叠区段标题(带折叠箭头与删除按钮, 数组项可删) */
function makeSectionHeader(label, path, value, isArrayItem) {
    const row = document.createElement('div');
    row.className = 'field-row';
    const tog = document.createElement('span');
    tog.className = 'field-toggle';
    tog.textContent = '▾';
    const keyEl = document.createElement('span');
    keyEl.className = 'field-key';
    keyEl.textContent = label;
    row.appendChild(tog);
    row.appendChild(keyEl);

    // 数组元素提供删除按钮
    if (isArrayItem && path.length > 0) {
        const del = document.createElement('button');
        del.className = 'icon-btn';
        del.title = '删除该项';
        del.textContent = '✕';
        del.addEventListener('click', (e) => {
            e.stopPropagation();
            deleteByPath(state.data, path);
            afterStructChange();
        });
        row.appendChild(del);
    }

    let collapsed = false;
    const toggle = () => {
        collapsed = !collapsed;
        let sib = row.nextElementSibling;
        while (sib) { sib.style.display = collapsed ? 'none' : ''; sib = sib.nextElementSibling; }
        tog.textContent = collapsed ? '▸' : '▾';
    };
    tog.addEventListener('click', toggle);
    keyEl.addEventListener('click', toggle);
    return row;
}

/* road_areas 紧凑行: name / description / polygon */
function renderRoadRow(item, path, idx) {
    const row = document.createElement('div');
    row.className = 'field-array-row';
    const idxEl = document.createElement('span');
    idxEl.className = 'idx';
    idxEl.textContent = idx;
    row.appendChild(idxEl);

    const nameInp = document.createElement('input');
    nameInp.type = 'text';
    nameInp.value = item.name || '';
    nameInp.placeholder = 'name';
    nameInp.style.width = '140px';
    nameInp.title = '道路名称';
    nameInp.addEventListener('change', () => {
        setByPath(state.data, path.concat('name'), nameInp.value);
        draw(); scheduleSyncText(); markDirty();
    });
    row.appendChild(nameInp);

    const descInp = document.createElement('input');
    descInp.type = 'text';
    descInp.value = item.description || '';
    descInp.placeholder = 'description';
    descInp.style.width = '180px';
    descInp.title = '描述';
    descInp.addEventListener('change', () => {
        setByPath(state.data, path.concat('description'), descInp.value);
        scheduleSyncText(); markDirty();
    });
    row.appendChild(descInp);

    // polygon 折叠区
    const polyBtn = document.createElement('button');
    polyBtn.className = 'icon-btn';
    polyBtn.textContent = '⌂';
    polyBtn.title = '展开/折叠 polygon 坐标';
    let polyOpen = false;
    const polyDiv = document.createElement('div');
    polyDiv.style.display = 'none';
    polyDiv.className = 'field-children';

    function renderRoadPolygonTuple(pt, ptPath, j) {
        const trow = document.createElement('div');
        trow.className = 'field-array-row';
        const tidx = document.createElement('span');
        tidx.className = 'idx'; tidx.textContent = j;
        trow.appendChild(tidx);
        const tuple = document.createElement('div');
        tuple.className = 'field-tuple';
        pt.forEach((n, axis) => {
            const inp = document.createElement('input');
            inp.type = 'number'; inp.value = n;
            inp.addEventListener('change', () => {
                const arr = getByPath(state.data, ptPath);
                arr[axis] = parseScalar(inp.value);
                draw(); scheduleSyncText(); markDirty();
            });
            tuple.appendChild(inp);
        });
        trow.appendChild(tuple);
        const del = document.createElement('button');
        del.className = 'icon-btn'; del.textContent = '✕'; del.title = '删除';
        del.addEventListener('click', () => {
            deleteByPath(state.data, ptPath);
            draw(); scheduleSyncText(); markDirty();
            refreshPoly(); polyDiv.style.display = '';
        });
        trow.appendChild(del);
        return trow;
    }
    function refreshPoly() {
        polyDiv.innerHTML = '';
        const polygon = getByPath(state.data, path.concat('polygon')) || item.polygon || [];
        polygon.forEach((pt, j) => {
            polyDiv.appendChild(renderRoadPolygonTuple(pt, path.concat('polygon', j), j));
        });
        polyDiv.appendChild(makeAddButton(path.concat('polygon'), () => {
            const arr = getByPath(state.data, path.concat('polygon'));
            arr.push([0, 0]);
            draw(); scheduleSyncText(); markDirty();
            refreshPoly(); polyDiv.style.display = '';
        }));
    }
    polyBtn.addEventListener('click', () => {
        polyOpen = !polyOpen;
        polyDiv.style.display = polyOpen ? '' : 'none';
        if (polyOpen) refreshPoly();
    });
    row.appendChild(polyBtn);

    const del = document.createElement('button');
    del.className = 'icon-btn';
    del.textContent = '✕';
    del.title = '删除道路';
    del.addEventListener('click', () => { deleteByPath(state.data, path); afterStructChange(); });
    row.appendChild(del);

    const wrap = document.createElement('div');
    wrap.className = 'field';
    wrap.appendChild(row);
    wrap.appendChild(polyDiv);
    return wrap;
}

/* beds_layout 紧凑行: bed_id / head_direction / head_position_mm */
function renderBedRow(item, path, idx) {
    const row = document.createElement('div');
    row.className = 'field-array-row';
    const idxEl = document.createElement('span');
    idxEl.className = 'idx';
    idxEl.textContent = item.bed_id || idx;
    row.appendChild(idxEl);

    const fields = [
        { k: 'bed_id', type: 'number', title: '床位ID' },
        { k: 'head_direction', type: 'select', options: ['north', 'south', 'east', 'west'], title: '床头向' },
        { k: 'head_position_mm', type: 'number', title: '床头线mm' },
    ];
    fields.forEach(f => {
        const inp = f.type === 'select' ? document.createElement('select') : document.createElement('input');
        if (f.type === 'select') {
            f.options.forEach(o => { const op = document.createElement('option'); op.value = o; op.textContent = o; if (item[f.k] === o) op.selected = true; inp.appendChild(op); });
        } else {
            inp.type = 'number';
            inp.value = item[f.k] ?? 0;
            inp.style.width = f.k === 'bed_id' ? '60px' : '110px';
        }
        inp.title = f.title;
        inp.addEventListener('change', () => {
            const v = f.type === 'number' ? parseScalar(inp.value) : inp.value;
            setByPath(state.data, path.concat(f.k), v);
            // 只刷新预览和 YAML 文本，不重绘表单，避免折叠
            draw();
            scheduleSyncText();
            markDirty();
        });
        row.appendChild(inp);
    });

    // polygon 作为子折叠区
    const polyBtn = document.createElement('button');
    polyBtn.className = 'icon-btn';
    polyBtn.textContent = '⌂';
    polyBtn.title = '展开/折叠 polygon 坐标';
    let polyOpen = false;
    const polyDiv = document.createElement('div');
    polyDiv.style.display = 'none';
    polyDiv.className = 'field-children';

    function renderBedPolygonTuple(pt, ptPath, j) {
        const row = document.createElement('div');
        row.className = 'field-array-row';
        const idxEl = document.createElement('span');
        idxEl.className = 'idx';
        idxEl.textContent = j;
        row.appendChild(idxEl);
        const tuple = document.createElement('div');
        tuple.className = 'field-tuple';
        pt.forEach((n, axis) => {
            const inp = document.createElement('input');
            inp.type = 'number';
            inp.value = n;
            inp.addEventListener('change', () => {
                const arr = getByPath(state.data, ptPath);
                arr[axis] = parseScalar(inp.value);
                draw();
                scheduleSyncText();
                markDirty();
            });
            tuple.appendChild(inp);
        });
        row.appendChild(tuple);
        const del = document.createElement('button');
        del.className = 'icon-btn';
        del.textContent = '✕';
        del.title = '删除';
        del.addEventListener('click', () => {
            deleteByPath(state.data, ptPath);
            draw();
            scheduleSyncText();
            markDirty();
            refreshPoly();
            polyDiv.style.display = '';
        });
        row.appendChild(del);
        return row;
    }

    function refreshPoly() {
        polyDiv.innerHTML = '';
        const polygon = getByPath(state.data, path.concat('polygon')) || item.polygon || [];
        polygon.forEach((pt, j) => {
            polyDiv.appendChild(renderBedPolygonTuple(pt, path.concat('polygon', j), j));
        });
        polyDiv.appendChild(makeAddButton(path.concat('polygon'), () => {
            const arr = getByPath(state.data, path.concat('polygon'));
            arr.push([0, 0]);
            draw();
            scheduleSyncText();
            markDirty();
            refreshPoly();
            // 保持展开状态
            polyDiv.style.display = '';
        }));
    }
    polyBtn.addEventListener('click', () => {
        polyOpen = !polyOpen;
        polyDiv.style.display = polyOpen ? '' : 'none';
        if (polyOpen) refreshPoly();
    });
    row.appendChild(polyBtn);

    const del = document.createElement('button');
    del.className = 'icon-btn';
    del.textContent = '✕';
    del.title = '删除';
    del.addEventListener('click', () => { deleteByPath(state.data, path); afterStructChange(); });
    row.appendChild(del);

    const wrap = document.createElement('div');
    wrap.className = 'field';
    wrap.appendChild(row);
    wrap.appendChild(polyDiv);
    return wrap;
}

/* arrangement 紧凑行: row / col / rotation / mirror */
function renderArrangementRow(item, path, idx) {
    const row = document.createElement('div');
    row.className = 'field-array-row';
    const idxEl = document.createElement('span');
    idxEl.className = 'idx';
    idxEl.textContent = idx;
    row.appendChild(idxEl);

    const fields = [
        { k: 'row', type: 'number', label: '行', width: '56px' },
        { k: 'col', type: 'number', label: '列', width: '56px' },
        { k: 'rotation', type: 'number', label: '旋转', width: '64px' },
        { k: 'mirror', type: 'select', label: '镜像', width: '110px', options: [
            { value: 'none', text: '无' },
            { value: 'vertical', text: '上下' },
            { value: 'horizontal', text: '左右' },
            { value: 'both', text: '双向' },
        ]},
    ];
    fields.forEach(f => {
        const wrap = document.createElement('label');
        wrap.className = 'field-inline-label';
        wrap.style.display = 'inline-flex'; wrap.style.alignItems = 'center'; wrap.style.gap = '3px';
        const lbl = document.createElement('span');
        lbl.textContent = f.label;
        lbl.style.color = 'var(--text-dim)';
        lbl.style.fontSize = '11px';
        wrap.appendChild(lbl);
        const inp = f.type === 'select' ? document.createElement('select') : document.createElement('input');
        if (f.type === 'select') {
            f.options.forEach(o => {
                const op = document.createElement('option');
                op.value = o.value; op.textContent = o.text;
                if (item[f.k] === o.value) op.selected = true;
                inp.appendChild(op);
            });
        } else {
            inp.type = 'number';
            inp.value = item[f.k];
        }
        inp.style.width = f.width || '72px';
        inp.title = f.k;
        inp.addEventListener('change', () => {
            const v = f.type === 'number' ? parseScalar(inp.value) : inp.value;
            setByPath(state.data, path.concat(f.k), v);
            afterStructChange();
        });
        wrap.appendChild(inp);
        row.appendChild(wrap);
    });

    const del = document.createElement('button');
    del.className = 'icon-btn';
    del.textContent = '✕';
    del.title = '删除';
    del.addEventListener('click', () => { deleteByPath(state.data, path); afterStructChange(); });
    row.appendChild(del);
    return row;
}

/* 数字数组紧凑行(如 [0,0]) */
function renderTupleRow(arr, path, idx) {
    const row = document.createElement('div');
    row.className = 'field-array-row';
    const idxEl = document.createElement('span');
    idxEl.className = 'idx';
    idxEl.textContent = idx;
    row.appendChild(idxEl);
    const tuple = document.createElement('div');
    tuple.className = 'field-tuple';
    arr.forEach((n, j) => {
        const inp = document.createElement('input');
        inp.type = 'number';
        inp.value = n;
        inp.addEventListener('change', () => {
            setByPath(state.data, path.concat(j), parseScalar(inp.value));
            afterStructChange();
        });
        tuple.appendChild(inp);
    });
    row.appendChild(tuple);
    const del = document.createElement('button');
    del.className = 'icon-btn';
    del.textContent = '✕';
    del.title = '删除';
    del.addEventListener('click', () => { deleteByPath(state.data, path); afterStructChange(); });
    row.appendChild(del);
    return row;
}

/* 标量行 */
function renderScalarRow(value, label, path) {
    const row = document.createElement('div');
    row.className = 'field-row';
    const spacer = document.createElement('span');
    spacer.className = 'field-toggle';
    spacer.textContent = '';
    const keyEl = document.createElement('span');
    keyEl.className = 'field-key';
    keyEl.textContent = label;
    row.appendChild(spacer);
    row.appendChild(keyEl);

    let inp;
    if (typeof value === 'boolean') {
        inp = document.createElement('input');
        inp.type = 'checkbox';
        inp.className = 'bool';
        inp.checked = value;
        inp.addEventListener('change', () => { setByPath(state.data, path, inp.checked); afterStructChange(); });
    } else if (typeof value === 'number') {
        inp = document.createElement('input');
        inp.type = 'number';
        inp.value = value;
        if (Number.isInteger(value)) inp.step = '1';
        inp.addEventListener('change', () => { setByPath(state.data, path, parseScalar(inp.value)); afterStructChange(); });
    } else {
        inp = document.createElement('input');
        inp.type = 'text';
        inp.value = value === null || value === undefined ? '' : String(value);
        inp.placeholder = value === null ? 'null' : '';
        inp.addEventListener('change', () => { setByPath(state.data, path, parseScalar(inp.value)); afterStructChange(); });
    }
    row.appendChild(inp);
    return row;
}

function makeAddButton(path, onClick) {
    const btn = document.createElement('button');
    btn.className = 'section-add';
    btn.textContent = '+ 添加';
    btn.addEventListener('click', onClick);
    return btn;
}

/* 深拷贝工具(简单版, 适用于 JSON 可序列化的配置数据) */
function deepClone(obj) {
    return JSON.parse(JSON.stringify(obj));
}

/* 记录历史快照(在结构性变更前调用) */
function pushHistory() {
    if (!state.data) return;
    // 如果当前不在历史末尾, 丢弃当前位置之后的记录( redo 分支 )
    if (state.historyIndex < state.history.length - 1) {
        state.history = state.history.slice(0, state.historyIndex + 1);
    }
    state.history.push(deepClone(state.data));
    if (state.history.length > state.historyMax) {
        state.history.shift();
    } else {
        state.historyIndex++;
    }
    updateUndoRedoButtons();
}

/* 撤销 */
function undo() {
    if (state.historyIndex <= 0) return;
    state.historyIndex--;
    state.data = deepClone(state.history[state.historyIndex]);
    restoreFromHistory();
    flash('已撤销', 'ok');
}

/* 重做 */
function redo() {
    if (state.historyIndex >= state.history.length - 1) return;
    state.historyIndex++;
    state.data = deepClone(state.history[state.historyIndex]);
    restoreFromHistory();
    flash('已重做', 'ok');
}

/* 从历史恢复后刷新界面 */
function restoreFromHistory() {
    renderProps(state.data);
    resetViewAndDraw();
    scheduleSyncText();
    markDirty();
    updateUndoRedoButtons();
}

function updateUndoRedoButtons() {
    if (els.btnUndo) els.btnUndo.disabled = state.historyIndex <= 0;
    if (els.btnRedo) els.btnRedo.disabled = state.historyIndex >= state.history.length - 1;
}

/* 结构变化后: 先记录历史, 再重渲染表单 + 重绘 + 同步文本 + 标记脏 */
function afterStructChange() {
    pushHistory();
    renderProps(state.data);
    draw();
    scheduleSyncText();
    markDirty();
}

/* ===================== Canvas 视图与绘制 ===================== */
const view = { scale: 1, ox: 0, oy: 0 };  // world->screen 变换(CSS px)
let cssW = 0, cssH = 0;

function resizeCanvas() {
    const dpr = window.devicePixelRatio || 1;
    const rect = els.canvas.getBoundingClientRect();
    cssW = rect.width; cssH = rect.height;
    els.canvas.width = Math.max(1, Math.floor(cssW * dpr));
    els.canvas.height = Math.max(1, Math.floor(cssH * dpr));
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    draw();
}

/* world(左下原点, y向上) -> screen */
function w2s(x, y) {
    return [view.ox + x * view.scale, cssH - view.oy - y * view.scale];
}
function s2w(sx, sy) {
    return [(sx - view.ox) / view.scale, (cssH - sy - view.oy) / view.scale];
}

function clearCanvas() {
    ctx.clearRect(0, 0, cssW, cssH);
}

function resetViewAndDraw() {
    fitView();
    draw();
}

function fitView() {
    const bbox = computeBBox();
    if (!bbox) { view.scale = 1; view.ox = cssW / 2; view.oy = cssH / 2; updateZoomLabel(); return; }
    const w = Math.max(bbox.maxx - bbox.minx, 1);
    const h = Math.max(bbox.maxy - bbox.miny, 1);
    const pad = 60;
    const sx = (cssW - pad * 2) / w;
    const sy = (cssH - pad * 2) / h;
    view.scale = Math.min(sx, sy);
    const cx = (bbox.minx + bbox.maxx) / 2;
    const cy = (bbox.miny + bbox.maxy) / 2;
    view.ox = cssW / 2 - cx * view.scale;
    view.oy = cssH / 2 - cy * view.scale;
    updateZoomLabel();
}

function updateZoomLabel() {
    els.zoomLabel.textContent = Math.round(view.scale * 100) + '%';
}

/* 计算内容的世界坐标包围盒 */
function computeBBox() {
    const d = state.data;
    if (!d) return null;
    if (state.cat === 'modules') {
        const L = (d.dimensions && d.dimensions.length_mm) || 0;
        const W = (d.dimensions && d.dimensions.width_mm) || 0;
        return { minx: 0, miny: 0, maxx: L, maxy: W };
    }
    if (state.cat === 'groups') {
        // 由 drawGroup 计算各群组包围盒并合并; 这里简单估算
        return computeGroupBBox(d);
    }
    return null;
}

/* ---- 绘制主入口 ---- */
function draw() {
    clearCanvas();
    if (!state.data) { els.canvasEmpty.classList.remove('hidden'); return; }
    els.canvasEmpty.classList.add('hidden');
    drawGrid();
    drawAxes();
    if (state.cat === 'modules') drawModule(state.data);
    else if (state.cat === 'groups') drawGroups(state.data);
}

/* 参考网格(以世界坐标, 自适应步长) */
function drawGrid() {
    const step = niceGridStep(40 / view.scale);
    ctx.save();
    ctx.lineWidth = 1;
    ctx.strokeStyle = 'rgba(255,255,255,0.04)';
    ctx.beginPath();
    const [wx0, wy0] = s2w(0, cssH);
    const [wx1, wy1] = s2w(cssW, 0);
    const x0 = Math.floor(wx0 / step) * step;
    const x1 = Math.ceil(wx1 / step) * step;
    const y0 = Math.floor(wy0 / step) * step;
    const y1 = Math.ceil(wy1 / step) * step;
    for (let x = x0; x <= x1; x += step) { const [sx] = w2s(x, 0); ctx.moveTo(sx, 0); ctx.lineTo(sx, cssH); }
    for (let y = y0; y <= y1; y += step) { const [, sy] = w2s(0, y); ctx.moveTo(0, sy); ctx.lineTo(cssW, sy); }
    ctx.stroke();
    ctx.restore();
}

/* 坐标轴(原点 + X/Y 方向标识) */
function drawAxes() {
    const [ox, oy] = w2s(0, 0);
    ctx.save();
    ctx.lineWidth = 1.5;
    ctx.strokeStyle = 'rgba(255,120,120,0.5)';
    ctx.beginPath(); ctx.moveTo(ox, 0); ctx.lineTo(ox, cssH); ctx.stroke();
    ctx.strokeStyle = 'rgba(120,200,255,0.5)';
    ctx.beginPath(); ctx.moveTo(0, oy); ctx.lineTo(cssW, oy); ctx.stroke();
    ctx.fillStyle = '#8a8a8a'; ctx.font = '11px Consolas';
    ctx.fillText('X→', cssW - 22, oy - 6);
    ctx.fillText('Y↑', ox + 6, 12);
    ctx.restore();
}

function niceGridStep(target) {
    const pow = Math.pow(10, Math.floor(Math.log10(target)));
    const n = target / pow;
    let step;
    if (n < 1.5) step = 1;
    else if (n < 3) step = 2;
    else if (n < 7) step = 5;
    else step = 10;
    return step * pow;
}

/* ---- 箭头工具 ---- */
function drawArrow(x1, y1, x2, y2, color, width) {
    ctx.save();
    ctx.strokeStyle = color; ctx.fillStyle = color; ctx.lineWidth = width || 2;
    ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke();
    const ang = Math.atan2(y2 - y1, x2 - x1);
    const hs = 8;
    ctx.beginPath();
    ctx.moveTo(x2, y2);
    ctx.lineTo(x2 - hs * Math.cos(ang - Math.PI / 6), y2 - hs * Math.sin(ang - Math.PI / 6));
    ctx.lineTo(x2 - hs * Math.cos(ang + Math.PI / 6), y2 - hs * Math.sin(ang + Math.PI / 6));
    ctx.closePath(); ctx.fill();
    ctx.restore();
}

/* ---- 模块绘制 ---- */
function drawModule(d) {
    const dim = d.dimensions || {};
    const L = dim.length_mm || 0;
    const W = dim.width_mm || 0;
    const color = (d.visual && d.visual.color) || '#007acc';
    const singleTexture = (d.visual && d.visual.single_texture) || null;
    const [x0, y0] = w2s(0, 0);
    const [x1, y1] = w2s(L, W);

    // 外框与单体材质
    ctx.save();
    const tex = loadTexture(singleTexture);
    if (tex && tex.complete && !tex.failed) {
        ctx.drawImage(tex, x0, y1, x1 - x0, y0 - y1);
        ctx.fillStyle = hexToRgba(color, 0.15);
    } else {
        ctx.fillStyle = hexToRgba(color, 0.10);
    }
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.fillRect(x0, y1, x1 - x0, y0 - y1);
    ctx.strokeRect(x0, y1, x1 - x0, y0 - y1);
    ctx.restore();

    // 通道区域(半透明黄色)
    (d.road_areas || []).forEach(ra => {
        const poly = ra.polygon || [];
        if (poly.length < 2) return;
        ctx.save();
        ctx.fillStyle = 'rgba(204,170,0,0.35)';
        ctx.strokeStyle = 'rgba(204,170,0,0.8)';
        ctx.lineWidth = 1;
        ctx.beginPath();
        poly.forEach((p, i) => { const [sx, sy] = w2s(p[0], p[1]); if (i === 0) ctx.moveTo(sx, sy); else ctx.lineTo(sx, sy); });
        ctx.closePath(); ctx.fill(); ctx.stroke();
        // 通道名
        const cx = poly.reduce((a, p) => a + p[0], 0) / poly.length;
        const cy = poly.reduce((a, p) => a + p[1], 0) / poly.length;
        const [lcx, lcy] = w2s(cx, cy);
        ctx.fillStyle = '#ffe79a'; ctx.font = '11px Consolas'; ctx.textAlign = 'center';
        ctx.fillText(ra.name || '通道', lcx, lcy);
        ctx.restore();
    });

    // 床位空间(半透明边框 + 独立床头方向)
    const bedsLayout = d.beds_layout || [];
    bedsLayout.forEach((bed, idx) => {
        drawBedSpace(bed, idx, color);
    });



    // 标注: 名称 + 类型 + 尺寸
    ctx.save();
    ctx.fillStyle = '#fff'; ctx.font = 'bold 13px Segoe UI'; ctx.textAlign = 'left';
    ctx.fillText(`${d.name || ''} (${d.module_id || ''})`, x0 + 6, y1 - 8);
    ctx.fillStyle = '#9cdcfe'; ctx.font = '11px Segoe UI';
    ctx.fillText(`类型: ${d.type || ''}  床位: ${d.beds ?? ''}`, x0 + 6, y1 - 24);
    ctx.fillStyle = '#cccccc'; ctx.font = '11px Consolas';
    ctx.fillText(`${L} × ${W} mm`, x0 + 6, y0 + 14);
    ctx.restore();

    // 图例
    const legendItems = [
        { color: color, label: '模块外框' },
        { color: 'rgba(204,170,0,0.6)', label: '通道区域 road_areas' },
    ];
    if (bedsLayout.length) {
        legendItems.push({ color: 'rgba(100,220,180,0.6)', label: '床位空间 beds_layout' });
        legendItems.push({ color: '#ff6b6b', label: '床位床头方向' });
    } else {
        legendItems.push({ color: '#ff6b6b', label: '模块床头方向' });
    }
    showLegend(legendItems);
}

/* 绘制单个床位空间: 半透明填充 + 虚线边框 + 床位ID + 独立床头方向 */
function drawBedSpace(bed, idx, color) {
    const poly = bed.polygon || [];
    if (poly.length < 3) return;

    // 床位多边形
    ctx.save();
    ctx.fillStyle = 'rgba(100,220,180,0.18)';
    ctx.strokeStyle = 'rgba(100,220,180,0.85)';
    ctx.lineWidth = 1.5;
    ctx.setLineDash([4, 2]);
    ctx.beginPath();
    poly.forEach((p, i) => { const [sx, sy] = w2s(p[0], p[1]); if (i === 0) ctx.moveTo(sx, sy); else ctx.lineTo(sx, sy); });
    ctx.closePath(); ctx.fill(); ctx.stroke();
    ctx.setLineDash([]);

    // 床位中心
    const cx = poly.reduce((a, p) => a + p[0], 0) / poly.length;
    const cy = poly.reduce((a, p) => a + p[1], 0) / poly.length;
    const [scx, scy] = w2s(cx, cy);
    ctx.fillStyle = 'rgba(100,220,180,0.9)'; ctx.font = 'bold 11px Consolas'; ctx.textAlign = 'center';
    ctx.fillText(`床${bed.bed_id || idx + 1}`, scx, scy + 3);
    ctx.restore();

    // 床位自己的床头方向(传入床位实际多边形)
    const bo = {
        head_direction: bed.head_direction,
    };
    drawBedOrientation(bo, poly, String(bed.bed_id || idx + 1));
}

/* 绘制床头方向
   参数 poly 为床位多边形(世界坐标mm); label 为标签(床位用)
   绘制方式: 贴着靠近床头方向的那条边画一条粗线, 并画一个向外的箭头 */
function drawBedOrientation(bo, poly, label = null) {
    const dir = bo.head_direction;
    if (!dir || !poly || poly.length < 3) return;

    // 计算床位边界
    let minx = Infinity, maxx = -Infinity, miny = Infinity, maxy = -Infinity;
    poly.forEach(p => {
        minx = Math.min(minx, p[0]); maxx = Math.max(maxx, p[0]);
        miny = Math.min(miny, p[1]); maxy = Math.max(maxy, p[1]);
    });

    // 找出床头方向对应的边: 取多边形中在目标方向上的顶点所形成的边
    // 简化处理: 对于矩形/凸多边形, 床头边就是 maxy(north)/miny(south)/maxx(east)/minx(west) 那条边
    let headEdge = [];
    const tol = 1; // mm 容差
    if (dir === 'north') {
        headEdge = poly.filter(p => Math.abs(p[1] - maxy) < tol);
    } else if (dir === 'south') {
        headEdge = poly.filter(p => Math.abs(p[1] - miny) < tol);
    } else if (dir === 'east') {
        headEdge = poly.filter(p => Math.abs(p[0] - maxx) < tol);
    } else if (dir === 'west') {
        headEdge = poly.filter(p => Math.abs(p[0] - minx) < tol);
    }

    // 如果过滤后不足2点, 退化为使用边界框的边
    if (headEdge.length < 2) {
        if (dir === 'north') headEdge = [[minx, maxy], [maxx, maxy]];
        else if (dir === 'south') headEdge = [[minx, miny], [maxx, miny]];
        else if (dir === 'east') headEdge = [[maxx, miny], [maxx, maxy]];
        else if (dir === 'west') headEdge = [[minx, miny], [minx, maxy]];
    }

    // 按顺时针/逆时针排序, 让线段连续
    if (dir === 'north' || dir === 'south') {
        headEdge.sort((a, b) => a[0] - b[0]);
    } else {
        headEdge.sort((a, b) => a[1] - b[1]);
    }

    ctx.save();
    ctx.strokeStyle = '#ff6b6b';
    ctx.fillStyle = '#ff6b6b';
    ctx.lineWidth = 4;
    ctx.lineCap = 'round';

    // 画床头边线
    ctx.beginPath();
    headEdge.forEach((p, i) => {
        const [sx, sy] = w2s(p[0], p[1]);
        if (i === 0) ctx.moveTo(sx, sy); else ctx.lineTo(sx, sy);
    });
    ctx.stroke();

    // 画箭头: 从床头边中点向外指
    const mx = headEdge.reduce((a, p) => a + p[0], 0) / headEdge.length;
    const my = headEdge.reduce((a, p) => a + p[1], 0) / headEdge.length;
    const [cx, cy] = w2s(mx, my);
    let ax = mx, ay = my;
    const arrowLen = Math.min(maxx - minx, maxy - miny) * 0.25;
    if (dir === 'north') ay = my + arrowLen;
    else if (dir === 'south') ay = my - arrowLen;
    else if (dir === 'east') ax = mx + arrowLen;
    else if (dir === 'west') ax = mx - arrowLen;
    const [ax2, ay2] = w2s(ax, ay);
    drawArrow(cx, cy, ax2, ay2, '#ff6b6b', 2.5);

    // 标签: 放在床头边内侧
    let lx = mx, ly = my;
    const offset = Math.min(maxx - minx, maxy - miny) * 0.15;
    if (dir === 'north') ly = my - offset;
    else if (dir === 'south') ly = my + offset;
    else if (dir === 'east') lx = mx - offset;
    else if (dir === 'west') lx = mx + offset;
    const [lsx, lsy] = w2s(lx, ly);
    ctx.fillStyle = '#ff6b6b'; ctx.font = 'bold 10px Segoe UI'; ctx.textAlign = 'center';
    ctx.fillText(label || '床头', lsx, lsy + 3);
    ctx.restore();
}

/* ---- 群组绘制 ---- */
// 安全读取间距数值(米), 缺失返回 null
function spVal(obj, key) { return (obj && typeof obj[key] === 'number') ? obj[key] : null; }

// 群组预览间距(mm): 取群组间水平间距, 回退 2m
function groupPreviewGap(g) {
    const v = spVal(g && g.external_spacing, 'horizontal_gap_m');
    return v != null ? v * 1000 : 2000;
}

// 画带标签的间距条带(世界坐标)
function drawSpacingBand(x0, y0, x1, y1, label, color) {
    const [sx0, sy0] = w2s(x0, y0);
    const [sx1, sy1] = w2s(x1, y1);
    const minX = Math.min(sx0, sx1), minY = Math.min(sy0, sy1);
    const w = Math.abs(sx1 - sx0), h = Math.abs(sy1 - sy0);
    if (w <= 0.5 && h <= 0.5) return;
    ctx.save();
    ctx.fillStyle = color;
    ctx.fillRect(minX, minY, w, h);
    if (label && Math.max(w, h) > 14) {
        ctx.fillStyle = '#fff'; ctx.font = 'bold 10px Segoe UI';
        ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
        ctx.fillText(label, minX + w / 2, minY + h / 2);
    }
    ctx.restore();
}

function computeGroupBBox(d) {
    const groups = d.groups || [];
    if (groups.length === 0) return null;
    let minx = 0, miny = 0, maxx = 0, maxy = 0, init = false;
    let cursorX = 0;
    const gap = groupPreviewGap(groups[0]); // 群组间间隔(mm, 仅用于预览排布)
    groups.forEach(g => {
        const mod = getModuleDims(d.module_id);
        const L = mod.L, W = mod.W;
        const hg = (g.internal_spacing && g.internal_spacing.horizontal_gap_m || 0) * 1000;
        const vg = (g.internal_spacing && g.internal_spacing.vertical_gap_m || 0) * 1000;
        const cols = g.cols || 0, rows = g.rows || 0;
        const gw = cols * L + Math.max(0, cols - 1) * hg;
        const gh = rows * W + Math.max(0, rows - 1) * vg;
        if (!init) { minx = cursorX; miny = 0; maxx = cursorX + gw; maxy = gh; init = true; }
        else { maxx = Math.max(maxx, cursorX + gw); maxy = Math.max(maxy, gh); miny = Math.min(miny, 0); }
        cursorX += gw + gap;
    });
    return { minx, miny, maxx, maxy };
}

function drawGroups(d) {
    const groups = d.groups || [];
    if (groups.length === 0) return;
    const mod = getModuleDims(d.module_id);
    let cursorX = 0;
    const gap = groupPreviewGap(groups[0]);

    groups.forEach((g, i) => {
        drawSingleGroup(g, cursorX, 0, mod);
        const hg = (g.internal_spacing && g.internal_spacing.horizontal_gap_m || 0) * 1000;
        const vg = (g.internal_spacing && g.internal_spacing.vertical_gap_m || 0) * 1000;
        const gw = (g.cols || 0) * mod.L + Math.max(0, (g.cols || 0) - 1) * hg;
        const gh = (g.rows || 0) * mod.W + Math.max(0, (g.rows || 0) - 1) * vg;
        // 群组间间距条带(external_spacing 水平方向)
        if (i < groups.length - 1) {
            drawSpacingBand(cursorX + gw, 0, cursorX + gw + gap, gh, `外距H${gap / 1000}m`, 'rgba(255,120,120,0.16)');
        }
        cursorX += gw + gap;
    });

    // 图例: 镜像颜色 + 模块内部道路/床位 + 间距条带
    const modData = getModuleDims(d.module_id).data;
    const legendItems = [
        { color: MIRROR_COLORS.none, label: 'mirror: none' },
        { color: MIRROR_COLORS.vertical, label: 'mirror: vertical(上下)' },
        { color: MIRROR_COLORS.horizontal, label: 'mirror: horizontal(左右)' },
        { color: MIRROR_COLORS.both, label: 'mirror: both(双向)' },
    ];
    if (modData) {
        if ((modData.road_areas || []).length) legendItems.push({ color: 'rgba(204,170,0,0.6)', label: '模块内道路' });
        if ((modData.beds_layout || []).length) {
            legendItems.push({ color: 'rgba(100,220,180,0.6)', label: '模块内床位' });
            legendItems.push({ color: '#ff6b6b', label: '床位床头方向' });
        }
    }
    legendItems.push({ color: 'rgba(80,180,255,0.5)', label: '组内水平间距(internal H)' });
    legendItems.push({ color: 'rgba(255,200,80,0.5)', label: '组内垂直间距(internal V)' });
    legendItems.push({ color: 'rgba(255,120,120,0.5)', label: '群组间间距(external)' });
    showLegend(legendItems);
}

function drawSingleGroup(g, originX, originY, mod) {
    const L = mod.L, W = mod.W;
    const hg = (g.internal_spacing && g.internal_spacing.horizontal_gap_m || 0) * 1000;
    const vg = (g.internal_spacing && g.internal_spacing.vertical_gap_m || 0) * 1000;
    const cols = g.cols || 0, rows = g.rows || 0;
    const arr = normalizeArrangement(g.arrangement || []);

    // 群组外框
    const gw = cols * L + Math.max(0, cols - 1) * hg;
    const gh = rows * W + Math.max(0, rows - 1) * vg;
    const [bx0, by0] = w2s(originX, originY);
    const [bx1, by1] = w2s(originX + gw, originY + gh);
    ctx.save();
    ctx.strokeStyle = '#888'; ctx.lineWidth = 1.5; ctx.setLineDash([5, 3]);
    ctx.strokeRect(bx0, by1, bx1 - bx0, by0 - by1);
    ctx.setLineDash([]);
    ctx.restore();

    // 每个模块
    arr.forEach(item => {
        const col = item.col, row = item.row;
        const cellX = originX + col * (L + hg);
        const cellY = originY + row * (W + vg);
        drawModuleCell(cellX, cellY, L, W, item, g);
    });

    // 组内模块间间距条带(internal_spacing): 水平间隙(H) / 垂直间隙(V)
    if (hg > 0 && cols > 1) {
        for (let c = 1; c < cols; c++) {
            const x0 = originX + c * (L + hg) - hg;
            drawSpacingBand(x0, originY, x0 + hg, originY + gh, `H${hg / 1000}m`, 'rgba(80,180,255,0.20)');
        }
    }
    if (vg > 0 && rows > 1) {
        for (let r = 1; r < rows; r++) {
            const y0 = originY + r * (W + vg) - vg;
            drawSpacingBand(originX, y0, originX + gw, y0 + vg, `V${vg / 1000}m`, 'rgba(255,200,80,0.20)');
        }
    }

    // 群组标题 + 间距信息(组内 internal + 群组间 external, 均区分x/y)
    const ext = g.external_spacing || {};
    const eH = spVal(ext, 'horizontal_gap_m'), eV = spVal(ext, 'vertical_gap_m');
    ctx.save();
    ctx.fillStyle = '#fff'; ctx.font = 'bold 12px Segoe UI'; ctx.textAlign = 'left';
    ctx.fillText(`${g.group_type}  (${rows}×${cols}, ${g.module_count}模块)`, bx0, by1 - 6);
    ctx.font = '10px Segoe UI';
    ctx.fillStyle = '#8a8a8a';
    ctx.fillText(`优先级:${g.layout_priority || ''}  组内间距 H${(hg / 1000)}m/V${(vg / 1000)}m`, bx0, by1 - 20);
    ctx.fillStyle = '#ff7878';
    ctx.fillText(`群组间间距 H${eH != null ? eH : '-'}m/V${eV != null ? eV : '-'}m`, bx0, by1 - 34);
    ctx.restore();
}

function drawModuleCell(x, y, L, W, item, g) {
    const rot = (item.rotation || 0) * Math.PI / 180;
    const mirror = item.mirror || 'none';
    const color = MIRROR_COLORS[mirror] || MIRROR_COLORS.none;
    const modData = getModuleDims(state.data.module_id).data;
    const singleTexture = (modData && modData.visual && modData.visual.single_texture) || null;
    const rotation = item.rotation || 0;

    // 旋转围绕模块中心
    const cxw = x + L / 2, cyw = y + W / 2;
    const [cx, cy] = w2s(cxw, cyw);
    ctx.save();
    ctx.translate(cx, cy);
    // 屏幕坐标下 y 已翻转, 旋转方向需取反
    ctx.rotate(-rot);
    const sxL = L * view.scale, syW = W * view.scale;

    // 单体材质(按镜像翻转)
    const tex = loadTexture(singleTexture);
    if (tex && tex.complete && !tex.failed) {
        ctx.save();
        if (mirror === 'horizontal' || mirror === 'both') ctx.scale(-1, 1);
        if (mirror === 'vertical' || mirror === 'both') ctx.scale(1, -1);
        ctx.drawImage(tex, -sxL / 2, -syW / 2, sxL, syW);
        ctx.restore();
        ctx.fillStyle = hexToRgba(color, 0.35);
    } else {
        ctx.fillStyle = hexToRgba(color, 0.55);
    }
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.5;
    ctx.fillRect(-sxL / 2, -syW / 2, sxL, syW);
    ctx.strokeRect(-sxL / 2, -syW / 2, sxL, syW);

    // 镜像指示: 在模块内画一条床头线 + 箭头(简化)
    ctx.strokeStyle = 'rgba(255,255,255,0.7)'; ctx.lineWidth = 1.5;
    if (mirror === 'vertical' || mirror === 'both') {
        ctx.beginPath(); ctx.moveTo(-sxL / 2, 0); ctx.lineTo(sxL / 2, 0); ctx.stroke();
    }
    if (mirror === 'horizontal' || mirror === 'both') {
        ctx.beginPath(); ctx.moveTo(0, -syW / 2); ctx.lineTo(0, syW / 2); ctx.stroke();
    }

    // 行列标注
    ctx.fillStyle = '#fff'; ctx.font = 'bold 10px Consolas'; ctx.textAlign = 'center';
    ctx.fillText(`r${item.row}c${item.col}`, 0, 3);
    ctx.restore();

    // 旋转角度标注(若非0)
    if (item.rotation) {
        ctx.save();
        ctx.fillStyle = '#ffe79a'; ctx.font = '9px Consolas'; ctx.textAlign = 'left';
        ctx.fillText(`rot${item.rotation}°`, cx + sxL / 2 + 2, cy);
        ctx.restore();
    }

    // 绘制该模块实例内的道路与床位(使用模块配置数据)
    if (modData) {
        // 道路
        (modData.road_areas || []).forEach(ra => {
            const poly = ra.polygon || [];
            if (poly.length < 3) return;
            const worldPoly = poly.map(p => transformModulePointToWorld(p[0], p[1], L, W, x, y, rotation, mirror));
            drawRoadPolygonWorld(worldPoly, ra.name);
        });
        // 床位
        (modData.beds_layout || []).forEach((bed, idx) => {
            const poly = bed.polygon || [];
            if (poly.length < 3) return;
            const worldPoly = poly.map(p => transformModulePointToWorld(p[0], p[1], L, W, x, y, rotation, mirror));
            drawBedSpaceWorld(worldPoly, bed, idx, rotation, mirror);
        });
    }
}

/* 在世界坐标下绘制道路多边形 */
function drawRoadPolygonWorld(worldPoly, name) {
    ctx.save();
    ctx.fillStyle = 'rgba(204,170,0,0.35)';
    ctx.strokeStyle = 'rgba(204,170,0,0.8)';
    ctx.lineWidth = 1;
    ctx.beginPath();
    worldPoly.forEach((p, i) => {
        const [sx, sy] = w2s(p[0], p[1]);
        if (i === 0) ctx.moveTo(sx, sy); else ctx.lineTo(sx, sy);
    });
    ctx.closePath(); ctx.fill(); ctx.stroke();
    const cx = worldPoly.reduce((a, p) => a + p[0], 0) / worldPoly.length;
    const cy = worldPoly.reduce((a, p) => a + p[1], 0) / worldPoly.length;
    const [lcx, lcy] = w2s(cx, cy);
    ctx.fillStyle = '#ffe79a'; ctx.font = '10px Consolas'; ctx.textAlign = 'center';
    ctx.fillText(name || '通道', lcx, lcy);
    ctx.restore();
}

/* 在世界坐标下绘制单个床位空间 */
function drawBedSpaceWorld(worldPoly, bed, idx, rotationDeg, mirror) {
    ctx.save();
    ctx.fillStyle = 'rgba(100,220,180,0.18)';
    ctx.strokeStyle = 'rgba(100,220,180,0.85)';
    ctx.lineWidth = 1.5;
    ctx.setLineDash([4, 2]);
    ctx.beginPath();
    worldPoly.forEach((p, i) => {
        const [sx, sy] = w2s(p[0], p[1]);
        if (i === 0) ctx.moveTo(sx, sy); else ctx.lineTo(sx, sy);
    });
    ctx.closePath(); ctx.fill(); ctx.stroke();
    ctx.setLineDash([]);

    const cx = worldPoly.reduce((a, p) => a + p[0], 0) / worldPoly.length;
    const cy = worldPoly.reduce((a, p) => a + p[1], 0) / worldPoly.length;
    const [scx, scy] = w2s(cx, cy);
    ctx.fillStyle = 'rgba(100,220,180,0.9)'; ctx.font = 'bold 10px Consolas'; ctx.textAlign = 'center';
    ctx.fillText(`床${bed.bed_id || idx + 1}`, scx, scy + 3);
    ctx.restore();

    const effectiveDir = transformDirection(bed.head_direction, rotationDeg || 0, mirror || 'none');
    drawBedOrientation({ head_direction: effectiveDir }, worldPoly, String(bed.bed_id || idx + 1));
}

/* 获取模块尺寸(mm), 带缓存; 无则用默认值 */
function getModuleDims(moduleId) {
    if (!moduleId) return { L: 4000, W: 4000, data: null };
    const cached = state.moduleCache[moduleId];
    if (cached && cached.data) {
        const dim = cached.data.dimensions || {};
        return { L: dim.length_mm || 4000, W: dim.width_mm || 4000, data: cached.data };
    }
    // 异步加载, 完成后用真实尺寸重新适配视图并重绘
    fetch(`/api/configs/modules/module_${String(moduleId).toLowerCase()}.yaml`)
        .then(r => r.ok ? r.json() : null)
        .then(res => {
            if (res) {
                state.moduleCache[moduleId] = res;
                if (state.cat === 'groups') { fitView(); draw(); }
                else draw();
            }
        })
        .catch(() => {});
    return { L: 4000, W: 4000, data: null };
}

/* 将局部朝向(北/南/东/西)按 镜像->旋转 转换为世界朝向 */
function transformDirection(localDir, rotationDeg, mirror) {
    const ccw = ['north', 'west', 'south', 'east']; // 逆时针顺序
    let d = localDir;
    // 先应用镜像(模块局部坐标系内)
    if (mirror === 'vertical' || mirror === 'both') {
        if (d === 'north') d = 'south';
        else if (d === 'south') d = 'north';
    }
    if (mirror === 'horizontal' || mirror === 'both') {
        if (d === 'east') d = 'west';
        else if (d === 'west') d = 'east';
    }
    // 再应用旋转(世界坐标系逆时针)
    const steps = Math.round((((rotationDeg % 360) + 360) % 360) / 90) % 4;
    const idx = ccw.indexOf(d);
    if (idx >= 0) d = ccw[(idx + steps) % 4];
    return d;
}

/* 将模块局部坐标(左下原点, y向上)按 镜像->旋转->平移 转换为世界坐标 */
function transformModulePointToWorld(px, py, L, W, x, y, rotDeg, mirror) {
    let mx = px, my = py;
    if (mirror === 'vertical') my = W - py;
    else if (mirror === 'horizontal') mx = L - px;
    else if (mirror === 'both') { mx = L - px; my = W - py; }

    const dx = mx - L / 2;
    const dy = my - W / 2;
    const rad = rotDeg * Math.PI / 180;
    const cos = Math.cos(rad), sin = Math.sin(rad);
    const wx = x + L / 2 + dx * cos - dy * sin;
    const wy = y + W / 2 + dx * sin + dy * cos;
    return [wx, wy];
}

/* arrangement 元素归一化为 {row,col,rotation,mirror} */
function normalizeArrangement(arr) {
    return (arr || []).map(item => {
        if (isObject(item)) {
            return {
                row: Number(item.row) || 0,
                col: Number(item.col) || 0,
                rotation: Number(item.rotation) || 0,
                mirror: item.mirror || 'none',
            };
        }
        if (typeof item === 'string') {
            const m = item.match(/row:\s*(\d+).*col:\s*(\d+).*rotation:\s*(\d+).*mirror:\s*([A-Za-z_]+)/);
            if (m) return { row: +m[1], col: +m[2], rotation: +m[3], mirror: m[4] };
        }
        return { row: 0, col: 0, rotation: 0, mirror: 'none' };
    });
}

/* ---- 图例 ---- */
function showLegend(items) {
    els.legend.innerHTML = '';
    items.forEach(it => {
        const d = document.createElement('div');
        d.className = 'legend-item';
        d.innerHTML = `<span class="legend-swatch" style="background:${it.color}"></span>${it.label}`;
        els.legend.appendChild(d);
    });
    els.legend.classList.remove('hidden');
}

/* ---- 颜色工具 ---- */
function hexToRgba(hex, alpha) {
    if (!hex || hex[0] !== '#') return `rgba(0,122,204,${alpha})`;
    let h = hex.slice(1);
    if (h.length === 3) h = h.split('').map(c => c + c).join('');
    const r = parseInt(h.slice(0, 2), 16);
    const g = parseInt(h.slice(2, 4), 16);
    const b = parseInt(h.slice(4, 6), 16);
    return `rgba(${r},${g},${b},${alpha})`;
}

/* ===================== 交互: 平移 / 缩放 ===================== */
let dragging = false, lastX = 0, lastY = 0;
els.canvas.addEventListener('mousedown', (e) => {
    dragging = true; lastX = e.clientX; lastY = e.clientY;
    els.canvas.classList.add('dragging');
});
window.addEventListener('mousemove', (e) => {
    if (!dragging) return;
    const dx = e.clientX - lastX, dy = e.clientY - lastY;
    lastX = e.clientX; lastY = e.clientY;
    view.ox += dx; view.oy -= dy;
    draw();
});
window.addEventListener('mouseup', () => { dragging = false; els.canvas.classList.remove('dragging'); });

els.canvas.addEventListener('wheel', (e) => {
    e.preventDefault();
    const rect = els.canvas.getBoundingClientRect();
    const mx = e.clientX - rect.left, my = e.clientY - rect.top;
    const [wx, wy] = s2w(mx, my);
    const factor = e.deltaY < 0 ? 1.15 : 1 / 1.15;
    view.scale = Math.max(0.01, Math.min(200, view.scale * factor));
    // 保持鼠标处世界点不变
    view.ox = mx - wx * view.scale;
    view.oy = cssH - my - wy * view.scale;
    updateZoomLabel();
    draw();
}, { passive: false });

els.btnFit.addEventListener('click', () => { fitView(); draw(); });
els.btnReset.addEventListener('click', () => { fitView(); draw(); });
els.btnZoomIn.addEventListener('click', () => { zoomAtCenter(1.2); });
els.btnZoomOut.addEventListener('click', () => { zoomAtCenter(1 / 1.2); });
function zoomAtCenter(factor) {
    const mx = cssW / 2, my = cssH / 2;
    const [wx, wy] = s2w(mx, my);
    view.scale = Math.max(0.01, Math.min(200, view.scale * factor));
    view.ox = mx - wx * view.scale;
    view.oy = cssH - my - wy * view.scale;
    updateZoomLabel(); draw();
}

/* ===================== 分隔条拖动 ===================== */
(function setupResizer() {
    let dragging = false;
    els.resizer.addEventListener('mousedown', (e) => { dragging = true; e.preventDefault(); });
    window.addEventListener('mousemove', (e) => {
        if (!dragging) return;
        const rect = els.center.getBoundingClientRect();
        const h = rect.height;
        let yh = e.clientY - rect.top;
        yh = Math.max(80, Math.min(h - 80, yh));
        els.yamlPane.style.flex = `0 0 ${yh}px`;
    });
    window.addEventListener('mouseup', () => { dragging = false; });
})();

/* ===================== 事件绑定 ===================== */
els.tabs.forEach(t => t.addEventListener('click', () => loadList(t.dataset.cat)));
els.search.addEventListener('input', renderList);
els.btnUndo.addEventListener('click', undo);
els.btnRedo.addEventListener('click', redo);
els.btnApply.addEventListener('click', applyYaml);
els.btnSave.addEventListener('click', save);
els.yaml.addEventListener('input', () => { if (!suppressSync) markDirty(); });

/* 快捷键: Ctrl+S 保存, Ctrl+Z 撤销, Ctrl+Y 重做 */
window.addEventListener('keydown', (e) => {
    if (e.ctrlKey || e.metaKey) {
        const k = e.key.toLowerCase();
        if (k === 's') { e.preventDefault(); save(); }
        else if (k === 'z') { e.preventDefault(); undo(); }
        else if (k === 'y') { e.preventDefault(); redo(); }
    }
});

/* ResizeObserver: 画布尺寸变化时重绘 */
const ro = new ResizeObserver(() => resizeCanvas());
ro.observe(els.canvas.parentElement);

/* ===================== 启动排布弹窗 ===================== */
const layoutEls = {
    modal: $('#layout-modal'),
    btnOpen: $('#btn-run-layout'),
    btnClose: $('#layout-modal-close'),
    mode: $('#layout-mode'),
    evacuees: $('#layout-evacuees'),
    length: $('#layout-length'),
    width: $('#layout-width'),
    days: $('#layout-days'),
    strategy: $('#layout-strategy'),
    strategyItem: $('#layout-strategy-item'),
    recmode: $('#layout-recmode'),
    recmodeItem: $('#layout-recmode-item'),
    modulesSection: $('#layout-modules-section'),
    modulesList: $('#layout-modules-list'),
    btnRun: $('#btn-layout-run'),
    runStatus: $('#layout-run-status'),
    log: $('#layout-log'),
    logPre: $('#layout-log-pre'),
    result: $('#layout-result'),
    summary: $('#layout-summary'),
    png: $('#layout-png'),
    lightbox: $('#layout-lightbox'),
    lightboxImg: $('#lightbox-img'),
};

let moduleCatalogCache = null;

function openLayoutModal() {
    layoutEls.modal.classList.remove('hidden');
    syncLayoutModeUI();
}

function closeLayoutModal() {
    layoutEls.modal.classList.add('hidden');
}

/* 模式切换时显示/隐藏 策略/排布目标 与 模块数量 区块 */
function syncLayoutModeUI() {
    const isGen = layoutEls.mode.value === 'generate';
    layoutEls.strategyItem.classList.toggle('hidden', isGen);
    layoutEls.recmodeItem.classList.toggle('hidden', isGen);
    layoutEls.modulesSection.classList.toggle('hidden', !isGen);
    if (isGen) loadModuleQtyList();
}

/* 加载模块目录并渲染数量输入行(generate 模式) */
async function loadModuleQtyList() {
    if (!moduleCatalogCache) {
        try {
            moduleCatalogCache = await apiGet('/api/modules/catalog');
        } catch (e) {
            layoutEls.modulesList.innerHTML = `<div class="props-empty">加载模块目录失败: ${e.message}</div>`;
            return;
        }
    }
    layoutEls.modulesList.innerHTML = '';
    moduleCatalogCache.forEach(m => {
        const row = document.createElement('div');
        row.className = 'module-qty-row';
        const swatch = document.createElement('span');
        swatch.className = 'legend-swatch';
        swatch.style.background = m.color || '#444';
        const nameEl = document.createElement('span');
        nameEl.className = 'module-name';
        nameEl.textContent = `${m.name} (${m.id})`;
        nameEl.title = `${m.type} · ${m.bedsPerUnit}床/模块 · ${m.costPerUnit}元/模块 · ${m.ruleText}`;
        const typeEl = document.createElement('span');
        typeEl.className = 'module-meta';
        typeEl.textContent = `${m.bedsPerUnit}床`;
        const inp = document.createElement('input');
        inp.type = 'number';
        inp.min = '0';
        inp.step = String(m.step || 1);
        inp.value = '0';
        inp.dataset.code = m.id;
        inp.dataset.step = String(m.step || 1);
        inp.title = m.ruleText;
        row.appendChild(swatch);
        row.appendChild(nameEl);
        row.appendChild(typeEl);
        row.appendChild(inp);
        layoutEls.modulesList.appendChild(row);
    });
}

/* 运行排布 */
async function runLayout() {
    const mode = layoutEls.mode.value;
    const payload = {
        mode,
        evacuees: parseScalar(layoutEls.evacuees.value),
        length: parseScalar(layoutEls.length.value),
        width: parseScalar(layoutEls.width.value),
        days: parseScalar(layoutEls.days.value),
        strategy: layoutEls.strategy.value || null,
        recommendationMode: layoutEls.recmode.value || 'match_input',
    };
    if (mode === 'generate') {
        const selected = {};
        layoutEls.modulesList.querySelectorAll('input[data-code]').forEach(inp => {
            const q = parseInt(inp.value, 10);
            if (q > 0) selected[inp.dataset.code] = q;
        });
        payload.selectedModules = selected;
    }

    // 参数校验
    if (!payload.evacuees || payload.evacuees < 1) { layoutEls.runStatus.textContent = '人数需 ≥ 1'; layoutEls.runStatus.className = 'status-msg err'; return; }
    if (!payload.length || payload.length <= 0 || !payload.width || payload.width <= 0) { layoutEls.runStatus.textContent = '场地长宽需为正数'; layoutEls.runStatus.className = 'status-msg err'; return; }
    if (mode === 'generate' && Object.keys(payload.selectedModules).length === 0) {
        layoutEls.runStatus.textContent = 'generate 模式需至少选择一个模块';
        layoutEls.runStatus.className = 'status-msg err';
        return;
    }

    layoutEls.btnRun.disabled = true;
    layoutEls.runStatus.textContent = '提交任务…';
    layoutEls.runStatus.className = 'status-msg';
    layoutEls.result.classList.add('hidden');
    layoutEls.log.classList.add('hidden');
    layoutEls.logPre.textContent = '';

    const startTime = performance.now();
    let pollTimer = null;

    function updateLogs(logs) {
        layoutEls.logPre.textContent = (logs || []).join('\n');
        layoutEls.logPre.parentElement.scrollTop = layoutEls.logPre.parentElement.scrollHeight;
    }

    function renderResult(res) {
        const s = res.summary || {};
        const mods = Object.entries(res.selectedModules || {}).map(([k, v]) => `${k}×${v}`).join(', ');
        const modeLabel = res.recommendationMode === 'fill' ? '排满场地' : '跟人数一致';
        layoutEls.summary.innerHTML =
            `<div><b>模式:</b> ${res.mode} · <b>目标:</b> ${modeLabel} · <b>类型:</b> ${res.spaceType || '-'}</div>` +
            `<div><b>模块:</b> ${mods || '-'}</div>` +
            `<div><b>床位:</b> ${s.totalBeds ?? '-'} / 目标 ${s.targetBeds ?? res.site?.evacuees ?? '-'} · <b>成本:</b> ${s.totalCost ?? '-'} · <b>模块数:</b> ${s.totalQuantity ?? '-'}</div>`;

        if (res.layout && res.layout.pngUrl) {
            const elapsed = ((performance.now() - startTime) / 1000).toFixed(1);
            layoutEls.png.src = res.layout.pngUrl + '?t=' + Date.now();
            layoutEls.summary.innerHTML +=
                `<div class="ok"><b>耗时:</b> ${elapsed}s · <b>图片:</b> ${res.layout.pngUrl}</div>`;
            layoutEls.result.classList.remove('hidden');
            console.log('[启动排布] 成功:', res.runId, '图片:', res.layout.pngUrl, '耗时:', elapsed + 's');
        } else {
            layoutEls.summary.innerHTML += '<div class="ferr">未生成布局图</div>';
            layoutEls.result.classList.remove('hidden');
            console.warn('[启动排布] 成功但未返回图片路径:', res);
        }
    }

    function showError(msg, detail) {
        layoutEls.runStatus.textContent = '失败: ' + msg;
        layoutEls.runStatus.className = 'status-msg err';
        layoutEls.summary.innerHTML =
            `<div class="ferr"><b>运行失败:</b></div>` +
            `<div class="ferr">- ${detail || msg}</div>` +
            `<div class="ferr">请检查参数(人数、场地尺寸)是否合法, 或尝试缩小模块数量/增大场地。</div>`;
        layoutEls.result.classList.remove('hidden');
        console.error('[启动排布] 失败:', detail || msg, '请求参数:', payload);
    }

    try {
        const started = await apiPost('/api/layout', payload);
        layoutEls.runStatus.textContent = `运行中 (${started.runId})`;
        layoutEls.runStatus.className = 'status-msg warn';
        layoutEls.log.classList.remove('hidden');
        const statusUrl = started.statusUrl;

        pollTimer = setInterval(async () => {
            try {
                const st = await apiGet(statusUrl);
                updateLogs(st.logs);
                if (st.done) {
                    clearInterval(pollTimer);
                    pollTimer = null;
                    layoutEls.btnRun.disabled = false;
                    if (st.error) {
                        let msg = st.error;
                        let detail = '';
                        try {
                            const idx = msg.indexOf('{');
                            if (idx >= 0) {
                                const j = JSON.parse(msg.slice(idx));
                                if (j.detail) { detail = j.detail; msg = j.detail; }
                            }
                        } catch (_) {}
                        showError(msg, detail);
                    } else if (st.result) {
                        layoutEls.runStatus.textContent = `完成 (${st.result.runId})`;
                        layoutEls.runStatus.className = 'status-msg ok';
                        renderResult(st.result);
                    }
                }
            } catch (e) {
                // 轮询出错时继续, 避免偶发网络抖动中断任务
                console.warn('[启动排布] 轮询状态失败:', e.message);
            }
        }, 500);
    } catch (e) {
        layoutEls.btnRun.disabled = false;
        let msg = e.message;
        let detail = '';
        try {
            const idx = msg.indexOf('{');
            if (idx >= 0) {
                const j = JSON.parse(msg.slice(idx));
                if (j.detail) { detail = j.detail; msg = j.detail; }
            }
        } catch (_) {}
        showError(msg, detail);
    }
}

/* 事件绑定 */
layoutEls.btnOpen.addEventListener('click', openLayoutModal);
layoutEls.btnClose.addEventListener('click', closeLayoutModal);
layoutEls.modal.addEventListener('click', (e) => { if (e.target === layoutEls.modal) closeLayoutModal(); });
layoutEls.mode.addEventListener('change', syncLayoutModeUI);
layoutEls.btnRun.addEventListener('click', runLayout);

/* 双击布局图放大查看(灯箱); 点击空白或按 Esc 关闭 */
function openLightbox(src) {
    if (!src) return;
    layoutEls.lightboxImg.src = src;
    layoutEls.lightbox.classList.remove('hidden');
}
function closeLightbox() {
    layoutEls.lightbox.classList.add('hidden');
}
layoutEls.png.addEventListener('dblclick', () => openLightbox(layoutEls.png.src));
layoutEls.lightbox.addEventListener('click', (e) => { if (e.target === layoutEls.lightbox) closeLightbox(); });
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeLightbox(); });

/* ===================== 启动 ===================== */
window.addEventListener('load', () => {
    resizeCanvas();
    loadList('modules');
});
