
async function checkIn() {

    const status = document.getElementById("status");
    const topic = document.getElementById("study_topic");

    // Make sure a topic was selected
    if (topic && !topic.value) {

        status.innerText =
            "Please select a study topic before checking in.";

        return;
    }


    try {

        // Send the selected topic to Flask
        const formData = new FormData();

        if (topic) {

            formData.append(
                "study_topic",
                topic.value
            );

        }


        const res = await fetch("/checkin", {

            method: "POST",

            body: formData

        });


        const data = await res.json();


        status.innerText =
            data.message;


        // Disable button after successful check-in
        if (res.ok) {

            const button =
                document.querySelector(".checkin-button");

            if (button) {

                button.disabled = true;

            }

        }

    }

    catch (error) {

        console.error(
            "Check-in error:",
            error
        );


        status.innerText =
            "Something went wrong while checking in.";

    }

}



async function loadAttendance() {

    try {

        const res =
            await fetch("/attendance");


        const data =
            await res.json();


        const list =
            document.getElementById("list");


        if (!list) return;


        list.innerHTML = "";


        data.forEach(item => {

            const li =
                document.createElement("li");


            li.textContent =
                item.name;


            list.appendChild(li);

        });


        const count =
            document.getElementById("count");


        if (count) {

            count.innerText =
                data.length;

        }

    }

    catch (error) {

        console.error(
            "Attendance loading error:",
            error
        );

    }

}

