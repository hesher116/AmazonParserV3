# Детальний опис логіки парсингу A+ контенту

## Як працює A+ парсинг (поточна реалізація)

### Крок 1: Пошук A+ секцій

**Для A+ Product:**
```python
specific_selectors = [
    '#productDescription_feature_div',      # Специфічний селектор
    '[data-feature-name="productDescription"]',  # Альтернативний
]

general_selectors = [
    '#aplus_feature_div',                   # Загальний A+ контейнер
    '#aplus',
    '.aplus-module',
    '[data-feature-name="aplus"]',
]
```

**Для A+ Brand:**
```python
specific_selectors = [
    '#aplusBrandStory_feature_div',
    '[data-feature-name="aplusBrandStory"]',
]
```

**Логіка пошуку:**
1. Спочатку перевіряє **специфічні селектори** (найбільш ймовірні)
2. Якщо не знайдено - перевіряє **загальні селектори**
3. Якщо після 3 селекторів нічого не знайдено - виходить (early exit)

### Крок 2: Визначення цільової секції

**Для специфічних селекторів:**
- Автоматично вважається цільовою секцією (без перевірки тексту)

**Для загальних селекторів:**
- Перевіряє текст секції (перші 200 символів)
- Шукає маркери:
  - A+ Product: "Product description", "Product Description"
  - A+ Brand: "From the brand", "From the Brand"

### Крок 3: Пошук зображень в секції

**Метод 1: Прямі img теги**
```python
images = section.find_elements(By.TAG_NAME, 'img')
```

**Метод 2: Вкладені зображення (якщо Метод 1 не знайшов)**
```python
nested_images = section.find_elements(By.CSS_SELECTOR, 'img, div img, span img, picture img')
```

**Метод 3: Зображення з data-атрибутами (якщо Метод 2 не знайшов)**
```python
data_images = section.find_elements(By.CSS_SELECTOR, '[data-a-dynamic-image], [data-old-hires], img[src*="media-amazon"]')
```

### Крок 4: Витягування URL з кожного зображення

**Використовується `_extract_high_res_url_from_element()` з `base_image_parser.py`:**

1. **Перевіряє `data-old-hires`** на елементі → батьківському
2. **Перевіряє `data-a-dynamic-image`** (JSON) на елементі → батьківському
   - Парсить JSON: `{"url1": [width, height], "url2": [width, height]}`
   - Вибирає найбільший розмір (width * height)
3. **Перевіряє `data-src`** (пропускає маленькі thumbnails)
4. **Перевіряє `src`** (пропускає маленькі та SVG)

**Після витягування URL:**
- Застосовується `get_high_res_url()` - **видаляє індикатори розміру**
- Перевіряється чи не excluded URL (video, 360, ad)
- Додається до списку якщо унікальний

### Крок 5: Парсинг каруселей

**Якщо знайдено кнопки "Next":**
```python
next_buttons = section.find_elements(
    By.CSS_SELECTOR, 
    '.a-carousel-goto-nextpage, [aria-label="Next"], .a-carousel-right'
)
```

**Логіка:**
1. Збирає початкові видимі зображення
2. Клікає "Next" до 20 разів
3. Після кожного кліку збирає нові зображення
4. **Зупиняється коли знаходить дублікат URL** (вже бачили це зображення)
5. Повертає всі унікальні URL

### Крок 6: Збереження зображень

1. Об'єднує зображення з секції + зображення з каруселей
2. Видаляє дублікати
3. Зберігає в папку:
   - A+ Product: `aplus_product/A+1.jpg`, `A+2.jpg`, ...
   - A+ Brand: `aplus_brand/brand1.jpg`, `brand2.jpg`, ...

## Важливі моменти

### 1. Scroll до секції
```python
self.browser.scroll_to_element(section)
self.browser._random_sleep(0.1, 0.2)
```
**Чому:** Тригерить lazy loading зображень

### 2. Early exit
```python
if idx >= max_selector_checks and not sections_found:
    return saved_images  # Виходить якщо не знайдено секцій
```
**Чому:** Не витрачає час на пошук неіснуючих секцій

### 3. Break після першої знайденої секції
```python
if saved_images:
    break  # Зупиняється після першої успішної секції
```
**Чому:** A+ контент зазвичай в одній секції

### 4. Каруселі зупиняються на дублікатах
```python
if url in seen_urls:
    return urls  # Зупиняється коли бачить дублікат
```
**Чому:** Не клікає безкінечно, якщо карусель зациклена

## Потенційні проблеми

### 1. Зображення не знаходяться
**Можливі причини:**
- Секція знайдена, але `img` теги не знаходяться
- Зображення завантажуються через JavaScript (lazy loading)
- Зображення в iframe або shadow DOM

**Рішення:** Додано 3 методи пошуку (прямі, вкладені, data-атрибути)

### 2. URL не витягуються
**Можливі причини:**
- `data-a-dynamic-image` на батьківському елементі, а не на `img`
- Зображення мають тільки маленькі `src` без data-атрибутів
- Зображення завантажуються динамічно

**Рішення:** `_extract_high_res_url_from_element()` перевіряє батьківський елемент

### 3. Каруселі не парсяться
**Можливі причини:**
- Кнопка "Next" не знаходиться
- Кнопка не клікабельна
- Зображення не оновлюються після кліку

**Рішення:** Детальне логування та обробка помилок

## Як перевірити вручну

### 1. Перевірити наявність секцій:
```javascript
// В консолі браузера
document.querySelectorAll('#productDescription_feature_div, #aplusBrandStory_feature_div').length
```

### 2. Перевірити зображення в секції:
```javascript
const section = document.querySelector('#productDescription_feature_div');
const images = section.querySelectorAll('img');
console.log(`Found ${images.length} images`);
images.forEach((img, i) => {
  console.log(`Image ${i}:`, {
    src: img.src,
    'data-old-hires': img.getAttribute('data-old-hires'),
    'data-a-dynamic-image': img.getAttribute('data-a-dynamic-image')?.substring(0, 100),
    'data-src': img.getAttribute('data-src'),
  });
});
```

### 3. Перевірити каруселі:
```javascript
const section = document.querySelector('#productDescription_feature_div');
const nextBtn = section.querySelector('.a-carousel-goto-nextpage, [aria-label="Next"]');
console.log('Next button found:', !!nextBtn);
```

### 4. Перевірити батьківські елементи:
```javascript
const section = document.querySelector('#productDescription_feature_div');
const images = section.querySelectorAll('img');
images.forEach((img, i) => {
  const parent = img.parentElement;
  console.log(`Image ${i} parent:`, {
    tag: parent.tagName,
    'data-old-hires': parent.getAttribute('data-old-hires'),
    'data-a-dynamic-image': parent.getAttribute('data-a-dynamic-image')?.substring(0, 100),
  });
});
```

## Детальне логування (додано)

Тепер A+ парсери логують:
- ✅ Всі атрибути кожного `img` елемента (`src`, `data-old-hires`, `data-a-dynamic-image`, `data-src`)
- ✅ Чи вдалося витягнути URL
- ✅ Чому URL був пропущений (invalid, excluded, duplicate)
- ✅ Який метод використано для витягування URL

**Приклад логів:**
```
[A+ product] Processing image 1/5...
  src: https://m.media-amazon.com/images/I/..._SL500_.jpg...
  data-old-hires: None
  data-a-dynamic-image: Present (length: 234)
  data-src: None
  ✓ Extracted URL: https://m.media-amazon.com/images/I/....jpg...
  ✓ Added URL 1: https://m.media-amazon.com/images/I/....jpg...
```

## Важливо про `get_high_res_url()`

**Нова логіка (після оптимізації):**
- Видаляє всі індикатори розміру (`_SL1280_`, `_AC_SL500_`, тощо)
- Amazon автоматично повертає максимальний розмір

**Це працює для:**
- ✅ Hero зображення
- ✅ Product Gallery (з ImageBlockATF)
- ✅ A+ контент (має працювати також!)

**Якщо A+ не працює:**
- Можливо зображення мають інші атрибути
- Можливо потрібен інший підхід для A+ контенту
- Логи покажуть що саме не працює

