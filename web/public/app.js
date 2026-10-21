import { createMemeActions } from './ui-actions.mjs';
import { captionFieldsHtml, createDownloadHref } from './ui-model.mjs';
import { createPhotoMemeActions } from './photo-meme.mjs';
import { createFitMemeActions } from './fit-meme.mjs';
import { renderAnalogs, renderFitCards } from './fit-view.mjs';

const $ = (selector) => document.querySelector(selector);
const promptInput = $('#prompt');
const form = $('#meme-form');
const resultArea = $('#result-area');
const status = $('#action-status');
let renderedEditorKey = '';

function render(state) {
  const hasResult = Boolean(state.result);
  resultArea.setAttribute('aria-busy', String(state.busy));
  $('#empty-preview').hidden = state.busy || hasResult;
  $('#loading-state').hidden = !state.busy || hasResult;
  $('#error-state').hidden = !state.error;
  $('#error-state').textContent = state.error || '';
  $('#meme-result').hidden = !hasResult;
  $('#fallback-area').hidden = !state.fallbackAvailable;
  $('#prefix-note').hidden = !state.result?.promptWasShortened;
  const imageAnalysisNote = $('#image-analysis-note');
  imageAnalysisNote.hidden = !state.imageAnalysisRequested;
  imageAnalysisNote.textContent = !state.imageAnalysisRequested
    ? ''
    : state.result?.visualCaptionsApplied
      ? 'Gemini looked at this image and used it to write these captions.'
      : state.result?.imageAnalysisSent
        ? 'Visual captioning with this image did not complete; the Imgflip draft is shown.'
      : state.result?.captionPolished
        ? 'Gemini wrote these captions from the situation and drafts; this image could not be sent.'
        : 'Gemini could not inspect this image, so the Imgflip draft captions are shown.';
  const rewriteNote = $('#prompt-rewrite-note');
  rewriteNote.hidden = !state.result?.jokeAngle;
  rewriteNote.textContent = state.result?.jokeAngle
    ? `Joke angle: “${state.result.jokeAngle}”`
    : '';
  $('#generate').disabled = state.busy;
  $('#try-another').disabled = state.busy;
  $('#render-captions').disabled = state.busy;
  $('#general-generate').disabled = state.busy;
  status.textContent = state.busy ? 'Finding the funniest fit…' : '';

  if (!hasResult) return;
  const { result } = state;
  const candidateList = $('#candidate-list');
  candidateList.replaceChildren();
  state.candidates.forEach((candidate, index) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = `candidate-card${index === state.selectedIndex ? ' is-selected' : ''}`;
    button.setAttribute('aria-pressed', String(index === state.selectedIndex));
    button.setAttribute('aria-label', `Select meme option ${index + 1}: ${candidate.promptIdea || candidate.templateId}`);
    const thumbnail = document.createElement('img');
    thumbnail.src = candidate.imageUrl;
    thumbnail.alt = '';
    thumbnail.loading = 'lazy';
    const label = document.createElement('span');
    label.textContent = `OPTION ${String(index + 1).padStart(2, '0')}`;
    const angle = document.createElement('small');
    angle.textContent = candidate.promptIdea || candidate.templateName || 'Meme option';
    button.append(thumbnail, label, angle);
    button.addEventListener('click', () => actions.selectCandidate(index));
    candidateList.append(button);
  });
  const batchNote = $('#batch-note');
  batchNote.hidden = !state.partial;
  batchNote.textContent = `Imgflip returned ${state.candidates.length} of ${state.requestedCount} requested options. You can still use these.`;
  $('#meme-image').src = result.imageUrl;
  $('#meme-image').alt = `Meme using ${result.templateName || 'the selected'} template`;
  $('#template-label').textContent = result.captionPolished ? 'CAPTIONS PUNCHED UP' : result.matchedTemplate ? 'MATCH FOUND' : 'MEME OPTION';
  const source = $('#source-link');
  source.href = result.pageUrl || `https://imgflip.com/meme/${encodeURIComponent(result.templateId)}`;

  const editorKey = JSON.stringify([result.templateId, result.texts]);
  if (editorKey !== renderedEditorKey) {
    $('#caption-form').innerHTML = captionFieldsHtml(result.texts);
    renderedEditorKey = editorKey;
  }
  try {
    $('#download-meme').href = createDownloadHref(result.imageUrl);
    $('#download-meme').hidden = false;
  } catch {
    $('#download-meme').hidden = true;
  }
}

const actions = createMemeActions({ fetchImpl: fetch, onState: render });

const photoForm = $('#photo-form');
const photoInput = $('#photo-input');

function trustedImgflipUrl(value, pathPrefix, hostname) {
  try {
    const url = new URL(value);
    return url.protocol === 'https:' && url.hostname === hostname && !url.port && !url.username && !url.password && url.pathname.startsWith(pathPrefix)
      ? url.href
      : null;
  } catch { return null; }
}

function buildMatchedTemplate(match, selectedAssetId) {
  const template = match.template;
  const sourceUrl = trustedImgflipUrl(template.source_url, '/meme/', 'imgflip.com');
  const imageUrl = trustedImgflipUrl(template.image_url, '/', 'i.imgflip.com');
  if (!sourceUrl || !imageUrl) return null;

  const article = document.createElement('article');
  article.className = 'matched-template';
  const thumbnail = document.createElement('img');
  thumbnail.src = imageUrl;
  thumbnail.alt = '';
  thumbnail.loading = 'lazy';
  thumbnail.referrerPolicy = 'no-referrer';
  article.append(thumbnail);

  const content = document.createElement('div');
  const heading = document.createElement('div');
  heading.className = 'matched-template-name';
  const name = document.createElement('span');
  name.textContent = template.name || 'Meme format';
  if (String(template.asset_id) === String(selectedAssetId)) {
    const selected = document.createElement('strong');
    selected.className = 'selected-match-label';
    selected.textContent = 'GEMINI PICK';
    name.append(' ', selected);
  }
  const link = document.createElement('a');
  link.href = sourceUrl;
  link.target = '_blank';
  link.rel = 'noreferrer';
  link.textContent = 'VIEW SOURCE ↗';
  heading.append(name, link);
  content.append(heading);

  const examples = document.createElement('ul');
  examples.className = 'example-captions';
  for (const example of (Array.isArray(match.example_captions) ? match.example_captions : []).slice(0, 8)) {
    const exampleUrl = trustedImgflipUrl(example.url, '/i/', 'imgflip.com');
    if (!exampleUrl || !example.author || !Array.isArray(example.box_texts)) continue;
    const item = document.createElement('li');
    const caption = document.createElement('span');
    caption.textContent = `“${example.box_texts.join(' / ')}”`;
    const credit = document.createElement('span');
    credit.className = 'example-credit';
    credit.append(document.createTextNode('Example by '));
    const author = document.createElement('a');
    author.href = exampleUrl;
    author.target = '_blank';
    author.rel = 'noreferrer';
    author.textContent = example.author;
    credit.append(author);
    item.append(caption, credit);
    examples.append(item);
  }
  if (examples.childElementCount) content.append(examples);
  article.append(content);
  article.dataset.selected = String(String(template.asset_id) === String(selectedAssetId));
  return article;
}

function renderPhoto(state) {
  $('#photo-error').hidden = !state.error;
  $('#photo-error').textContent = state.error || '';
  $('#make-photo-meme').disabled = state.busy;
  photoInput.disabled = state.busy;
  $('#photo-status').textContent = state.busy ? 'Reading the photo and finding a fitting format… The matcher may be waking up; this can take up to 30 s.' : '';
  const hasResult = Boolean(state.options.length);
  $('#photo-result').hidden = !hasResult;
  if (!hasResult) return;

  $('#photo-meme-image').src = state.imageUrl;
  $('#download-photo-meme').href = state.imageUrl;
  $('#download-photo-meme').download = `photo-meme-option-${state.optionIndex + 1}.png`;
  $('#photo-caption-label').textContent = `OPTION ${String(state.optionIndex + 1).padStart(2, '0')} · ${state.options[state.optionIndex].texts.join(' / ')}`;
  $('#photo-description').textContent = `Gemini’s scene description: ${state.description}`;
  const options = $('#photo-option-list');
  options.replaceChildren();
  state.options.forEach((option, index) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'photo-option';
    button.setAttribute('aria-pressed', String(index === state.optionIndex));
    button.textContent = `OPTION ${String(index + 1).padStart(2, '0')}`;
    button.addEventListener('click', () => photoActions.selectOption(index));
    options.append(button);
  });
  const templates = $('#matched-template-list');
  templates.replaceChildren();
  state.matches.forEach((match) => {
    const article = buildMatchedTemplate(match, state.selectedMatch.template.asset_id);
    if (article) templates.append(article);
  });
}

const photoActions = createPhotoMemeActions({ fetchImpl: fetch, onState: renderPhoto });

photoForm.addEventListener('submit', (event) => {
  event.preventDefault();
  const [file] = photoInput.files || [];
  if (!file) {
    $('#photo-error').textContent = 'Choose a photo to get started.';
    $('#photo-error').hidden = false;
    return;
  }
  photoActions.generate(file);
});

$('#download-meme').addEventListener('click', async (event) => {
  const href = event.currentTarget.href;
  if (!href || href.endsWith('#')) return;
  event.preventDefault();
  try {
    const response = await fetch(href);
    if (!response.ok) throw new Error('The meme could not be downloaded.');
    const blobUrl = URL.createObjectURL(await response.blob());
    const link = document.createElement('a');
    link.href = blobUrl;
    link.download = 'meme-moment.png';
    link.click();
    URL.revokeObjectURL(blobUrl);
  } catch {
    status.textContent = 'The meme could not be downloaded just now.';
  }
});

window.addEventListener('pagehide', () => {
  photoActions.dispose();
  fitActions.dispose();
});

function updateCount() {
  $('#prompt-count').textContent = `${promptInput.value.length} / 500`;
}

form.addEventListener('submit', (event) => {
  event.preventDefault();
  actions.generate(promptInput.value, 'matched', Number($('#meme-count').value), $('#analyze-images').checked);
});

$('#caption-form').addEventListener('submit', (event) => {
  event.preventDefault();
  const texts = [...event.currentTarget.querySelectorAll('[data-caption-index]')].map((field) => field.value);
  actions.updateCaptions(texts);
});

$('#caption-form').addEventListener('input', (event) => {
  const field = event.target.closest('[data-caption-index]');
  if (!field) return;
  const counter = field.parentElement.querySelector('.caption-field-count');
  if (counter) counter.textContent = `${field.value.length} / 500`;
});

$('#try-another').addEventListener('click', () => actions.generate(promptInput.value, 'matched', Number($('#meme-count').value), $('#analyze-images').checked));
$('#general-generate').addEventListener('click', () => {
  const state = actions.getState();
  actions.generateGeneral(promptInput.value, state.requestedCount, state.analyzeImages);
});
promptInput.addEventListener('input', updateCount);

document.querySelectorAll('.prompt-chip').forEach((chip) => {
  chip.addEventListener('click', () => {
    promptInput.value = chip.dataset.prompt || '';
    updateCount();
    promptInput.focus();
  });
});

// ---- Situation / photo-only / photo + situation tabs -------------------------------------------
const fitTabs = [...document.querySelectorAll('[data-fit-tab]')];
const photoWorkspace = $('#photo-workspace');

function showFitMode(mode) {
  fitTabs.forEach((tab) => tab.setAttribute('aria-selected', String(tab.dataset.fitTab === mode)));
  document.querySelectorAll('[data-fit-panel]').forEach((panel) => { panel.hidden = panel.dataset.fitPanel !== mode; });
  photoWorkspace.hidden = mode !== 'photo';
  $('#fit-error').hidden = true;
}

function renderFit(state) {
  $('#fit-error').hidden = !state.error;
  $('#fit-error').textContent = state.error || '';
  $('#fit-submit-situation').disabled = state.busy;
  $('#fit-submit-both').disabled = state.busy;
  $('#fit-status').textContent = state.busy
    ? 'Searching real viral captions and adapting the closest ones. This usually takes 15 to 30 seconds.'
    : (state.cards.length ? `Found ${state.cards.length} memes. Rate the ones that are funny for you.` : '');
  const hasResult = !state.busy && state.cards.length > 0;
  $('#fit-results').hidden = !hasResult;
  if (!hasResult) return;
  renderFitCards($('#fit-card-list'), state.cards, { onRate: (index, rating) => fitActions.rate(index, rating) });
  renderAnalogs($('#fit-analogs'), state.analogs);
}

const fitActions = createFitMemeActions({ fetchImpl: fetch, onState: renderFit });
fitTabs.forEach((tab) => tab.addEventListener('click', () => showFitMode(tab.dataset.fitTab)));
$('#fit-form-situation').addEventListener('submit', (event) => {
  event.preventDefault();
  fitActions.generate({ situation: $('#fit-situation-text').value, file: null });
});
$('#fit-form-both').addEventListener('submit', (event) => {
  event.preventDefault();
  const [file] = $('#fit-photo-input').files || [];
  if (!file) {
    $('#fit-error').textContent = 'Choose a photo first, or use the Situation tab for words only.';
    $('#fit-error').hidden = false;
    return;
  }
  fitActions.generate({ situation: $('#fit-both-text').value, file });
});
showFitMode('situation');
