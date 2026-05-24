document.addEventListener('DOMContentLoaded', () => {
    
    // Tab Navigation
    const navItems = document.querySelectorAll('.nav-item');
    const tabContents = document.querySelectorAll('.tab-content');

    navItems.forEach(item => {
        item.addEventListener('click', (e) => {
            e.preventDefault();
            
            // Remove active classes
            navItems.forEach(nav => nav.classList.remove('active'));
            tabContents.forEach(tab => tab.classList.remove('active'));
            
            // Add active to clicked
            item.classList.add('active');
            const targetId = item.getAttribute('data-tab');
            document.getElementById(`tab-${targetId}`).classList.add('active');
        });
    });

    // Settings API
    const settingsForm = document.getElementById('settings-form');
    
    // Fetch initial config
    fetch('/api/config')
        .then(res => res.json())
        .then(data => {
            if(data.default_mesh_node) document.getElementById('default_mesh_node').value = data.default_mesh_node;
            if(data.default_profile) document.getElementById('default_profile').value = data.default_profile;
            if(data.ui_port) document.getElementById('ui_port').value = data.ui_port;
        })
        .catch(err => console.error("Error fetching config:", err));

    // Save Settings
    settingsForm.addEventListener('submit', (e) => {
        e.preventDefault();
        
        const inputs = ['default_mesh_node', 'default_profile', 'ui_port'];
        let promises = inputs.map(id => {
            const val = document.getElementById(id).value;
            return fetch('/api/config', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ key: id, value: val })
            });
        });

        Promise.all(promises).then(() => {
            showToast('Settings saved successfully.');
        }).catch(() => {
            showToast('Failed to save settings.', true);
        });
    });

    function showToast(message, isError=false) {
        const toast = document.getElementById('toast');
        toast.textContent = message;
        if(isError) toast.style.backgroundColor = 'var(--color-red)';
        else toast.style.backgroundColor = 'var(--color-white)';
        
        toast.classList.add('show');
        setTimeout(() => toast.classList.remove('show'), 3000);
    }
});
