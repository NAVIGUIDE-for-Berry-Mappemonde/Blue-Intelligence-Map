import * as cheerio from 'cheerio';

async function testScrape() {
  try {
    const res = await fetch('https://oceanfdn.org/projects/');
    const html = await res.text();
    const $ = cheerio.load(html);
    
    const projects: any[] = [];
    $('.project-item, .post, article, .grid-item, .card').each((i, el) => {
      const titleEl = $(el).find('h2, h3, .title').first();
      const title = titleEl.text().trim();
      const url = $(el).find('a').first().attr('href') || '';
      const img = $(el).find('img').first().attr('src') || '';
      const desc = $(el).find('p').first().text().trim() || '';
      
      if (title && url) {
        projects.push({ title, url, img, desc });
      }
    });
    
    if (projects.length === 0) {
      // Try another selector
      $('a').each((i, el) => {
        const title = $(el).text().trim();
        const url = $(el).attr('href');
        if (title && url && url.includes('/projects/') && !url.endsWith('/projects/')) {
          const parent = $(el).parent();
          const img = parent.find('img').attr('src') || '';
          projects.push({ title, url, img });
        }
      });
    }
    
    console.log(JSON.stringify(projects.slice(0, 5), null, 2));
  } catch (e) {
    console.error(e);
  }
}

testScrape();
