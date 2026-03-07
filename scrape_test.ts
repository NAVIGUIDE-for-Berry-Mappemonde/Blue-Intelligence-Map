import * as cheerio from 'cheerio';

async function testScrape() {
  try {
    const res = await fetch('https://oceanfdn.org/projects/');
    const html = await res.text();
    const $ = cheerio.load(html);
    
    const projects: any[] = [];
    // Just guessing some common selectors, let's print the first few links to see
    $('a').each((i, el) => {
      const href = $(el).attr('href');
      if (href && href.includes('/projects/') && href !== 'https://oceanfdn.org/projects/') {
        projects.push({
          title: $(el).text().trim(),
          url: href
        });
      }
    });
    
    console.log(JSON.stringify(projects.slice(0, 10), null, 2));
  } catch (e) {
    console.error(e);
  }
}

testScrape();
