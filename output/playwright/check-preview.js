async page => {
 await page.goto('file:///C:/Users/viswe/OneDrive/Desktop/RelayQueue/src/relayqueue/ui/index.html');
 await page.getByText('Open RelayQueue at localhost:8000',{exact:true}).waitFor();
 if(await page.locator('aside').evaluate(el=>getComputedStyle(el).backgroundColor)==='rgba(0, 0, 0, 0)') throw new Error('Missing CSS');
 if(await page.getByRole('button',{name:'Connect',exact:true}).isEnabled()) throw new Error('File preview interactive');
 await page.goto('http://localhost:8000/');
}
