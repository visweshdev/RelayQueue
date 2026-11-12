async page => {
 await page.goto('file:///C:/Users/viswe/OneDrive/Desktop/RelayQueue/src/relayqueue/ui/index.html');
 await page.getByRole('link',{name:'Open local dashboard',exact:true}).waitFor();
 if(await page.locator('.sidebar').evaluate(el=>getComputedStyle(el).backgroundColor)==='rgba(0, 0, 0, 0)')throw Error('Missing CSS');
 if(await page.getByRole('button',{name:'Connect',exact:true}).isEnabled())throw Error('File preview interactive');
 await page.goto('http://localhost:8000/');
}
