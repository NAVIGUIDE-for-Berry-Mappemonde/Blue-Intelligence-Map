import * as cheerio from 'cheerio';

async function test() {
  const res = await fetch("https://oceanfdn.org/projects/");
  const html = await res.text();
  const $ = cheerio.load(html);
  
  const projects: any[] = [];
  $('a').each((i, el) => {
    const title = $(el).text().trim();
    const url = $(el).attr('href');
    if (title && title.length > 5 && url && url.includes('/projects/') && !url.endsWith('/projects/')) {
      const parent = $(el).parent().parent();
      projects.push({
        title,
        url,
        text: parent.text().trim().replace(/\s+/g, ' ').substring(0, 200)
      });
    }
  });
  console.log("TOF:", JSON.stringify(projects.slice(0, 3), null, 2));

  const res2 = await fetch("https://oceana.org/campaigns/");
  const html2 = await res2.text();
  const $2 = cheerio.load(html2);
  const projects2: any[] = [];
  $2('a').each((i, el) => {
    const title = $2(el).text().trim();
    const url = $2(el).attr('href');
    if (title && title.length > 5 && url && url.includes('/campaigns/') && !url.endsWith('/campaigns/')) {
      const parent = $2(el).parent().parent();
      projects2.push({
        title,
        url,
        text: parent.text().trim().replace(/\s+/g, ' ').substring(0, 200)
      });
    }
  });
  console.log("Oceana:", JSON.stringify(projects2.slice(0, 3), null, 2));
}
test();
