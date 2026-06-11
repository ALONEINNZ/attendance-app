async function checkIn() {
    const name = document.getElementById("name").value;

    if (!name) {
        alert("Enter your name");
        return;
    }

    const res = await fetch("/checkin", {
        method: "POST",
        headers: {
            "Content-Type": "application/json"
        },
        body: JSON.stringify({ name: name })
    });

    const data = await res.json();
    document.getElementById("status").innerText = data.message;
}

async function loadAttendance() {
    const res = await fetch("/attendance");
    const data = await res.json();

    const list = document.getElementById("list");
    if (!list) return;

    list.innerHTML = "";

    data.forEach(item => {
    const li = document.createElement("li");
    li.textContent = item.name; 
    list.appendChild(li);
});
const count = document.getElementById("count");
if (count) {
    count.innerText = data.length;
}
}