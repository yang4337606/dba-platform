// Flash message auto-dismiss
document.addEventListener('DOMContentLoaded', function() {
  document.querySelectorAll('.flash').forEach(function(el) {
    setTimeout(function() {
      el.style.transition = 'opacity 0.3s';
      el.style.opacity = '0';
      setTimeout(function() { el.remove(); }, 300);
    }, 4000);
  });

  // Upload zone drag & drop
  var zone = document.querySelector('.upload-zone');
  var fileInput = document.getElementById('file-input');
  if (zone && fileInput) {
    zone.addEventListener('click', function() { fileInput.click(); });
    zone.addEventListener('dragover', function(e) { e.preventDefault(); zone.classList.add('dragover'); });
    zone.addEventListener('dragleave', function() { zone.classList.remove('dragover'); });
    zone.addEventListener('drop', function(e) {
      e.preventDefault(); zone.classList.remove('dragover');
      if (e.dataTransfer.files.length) {
        fileInput.files = e.dataTransfer.files;
        document.querySelector('.upload-text').textContent = e.dataTransfer.files[0].name;
      }
    });
    fileInput.addEventListener('change', function() {
      if (fileInput.files.length) {
        document.querySelector('.upload-text').textContent = fileInput.files[0].name;
      }
    });
  }

  // Collapsible analysis sections
  document.querySelectorAll('.analysis-header').forEach(function(header) {
    header.addEventListener('click', function() {
      var body = this.nextElementSibling;
      if (body && body.classList.contains('analysis-body')) {
        body.style.display = body.style.display === 'none' ? 'block' : 'none';
      }
    });
  });

  // Confirm delete
  document.querySelectorAll('[data-confirm]').forEach(function(el) {
    el.addEventListener('click', function(e) {
      if (!confirm(this.dataset.confirm)) {
        e.preventDefault();
      }
    });
  });
});
