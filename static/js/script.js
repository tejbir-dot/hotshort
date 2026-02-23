const ribbon = document.querySelector('.plasma-ribbon');
window.addEventListener('mousemove', e => {
  const x = (e.clientX / window.innerWidth - 0.5) * 10;
  const y = (e.clientY / window.innerHeight - 0.5) * 10;
  ribbon.style.transform = `rotate(${8 + x * 0.3}deg) translateY(${y * 2}px)`;
});
document.querySelectorAll('.clip-form').forEach(form => {
  form.addEventListener('submit', e => {
    const btn = form.querySelector('.generate-btn');
    const spinner = form.querySelector('.loading-spinner');

    btn.classList.add('loading');
    btn.innerText = "Generating...";
    spinner.style.display = 'inline-block';
  });
});
